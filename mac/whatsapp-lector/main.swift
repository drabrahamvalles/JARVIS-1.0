// Lector de WhatsApp para JARVIS.
//
// Corre en una Mac siempre prendida (launchd, 6:00, 15:00 y 21:00). Copia el archivo
// local de WhatsApp, lee los mensajes nuevos SIN conectarse a WhatsApp, se queda solo con
// los que mencionan una fecha u hora (más un poco de contexto del mismo chat), salta los
// chats excluidos y manda el resto a POST /whatsapp/mensajes.
//
// Necesita «Acceso total al disco» para ESTE programa, y nada más.
// El token de JARVIS se lee del Llavero (servicio «jarvis», cuenta «token»); nunca de un archivo.
//
// Uso:
//   whatsapp-lector             revisa y manda
//   whatsapp-lector --revisar   solo comprueba el archivo y muestra conteos (no manda nada)

import Foundation
import Security
import SQLite3

let home = FileManager.default.homeDirectoryForCurrentUser
let configDir = home.appendingPathComponent(".jarvis")
let configURL = configDir.appendingPathComponent("whatsapp.json")
let stateURL = configDir.appendingPathComponent("whatsapp-estado.json")
let dbDir = home.appendingPathComponent(
    "Library/Group Containers/group.net.whatsapp.WhatsApp.shared")
// WhatsApp guarda las fechas en segundos desde el 1 de enero de 2001.
let appleEpoch: Double = 978_307_200
let contextBefore = 3
let contextAfter = 2

struct Config: Codable {
    let url: String
    var excluir: [String]? = []
}

struct State: Codable {
    var ultimo: Int64
}

struct Row {
    let pk: Int64
    let text: String
    let date: Double
    let fromMe: Bool
    let chatId: Int64
    let chatName: String
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

func keychainToken() -> String {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "jarvis",
        kSecAttrAccount as String: "token",
        kSecReturnData as String: true,
    ]
    var item: CFTypeRef?
    guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
        let data = item as? Data, let token = String(data: data, encoding: .utf8)
    else { fail("No encontré el token en el Llavero (servicio jarvis, cuenta token).") }
    return token.trimmingCharacters(in: .whitespacesAndNewlines)
}

// Copia la base (con su WAL) a una carpeta temporal para no tocar la de WhatsApp.
func snapshotDatabase() -> URL {
    let temp = FileManager.default.temporaryDirectory.appendingPathComponent(
        "jarvis-wa-\(UUID().uuidString)")
    try? FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
    for name in ["ChatStorage.sqlite", "ChatStorage.sqlite-wal", "ChatStorage.sqlite-shm"] {
        let source = dbDir.appendingPathComponent(name)
        if FileManager.default.fileExists(atPath: source.path) {
            do {
                try FileManager.default.copyItem(at: source, to: temp.appendingPathComponent(name))
            } catch {
                fail("No pude copiar \(name). ¿Este programa tiene Acceso total al disco?")
            }
        } else if name == "ChatStorage.sqlite" {
            fail("No encontré el archivo de WhatsApp. ¿Está instalado y con sesión iniciada?")
        }
    }
    return temp
}

func query(_ db: OpaquePointer?, _ sql: String, _ bind: (OpaquePointer?) -> Void = { _ in })
    -> [[Any?]]
{
    var statement: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK else {
        fail("La consulta falló: \(String(cString: sqlite3_errmsg(db)))")
    }
    defer { sqlite3_finalize(statement) }
    bind(statement)
    var rows: [[Any?]] = []
    while sqlite3_step(statement) == SQLITE_ROW {
        var row: [Any?] = []
        for column in 0..<sqlite3_column_count(statement) {
            switch sqlite3_column_type(statement, column) {
            case SQLITE_INTEGER: row.append(sqlite3_column_int64(statement, column))
            case SQLITE_FLOAT: row.append(sqlite3_column_double(statement, column))
            case SQLITE_TEXT: row.append(String(cString: sqlite3_column_text(statement, column)))
            default: row.append(nil)
            }
        }
        rows.append(row)
    }
    return rows
}

func number(_ value: Any?) -> Double {
    if let v = value as? Double { return v }
    if let v = value as? Int64 { return Double(v) }
    return 0
}

let messageSQL = """
    SELECT m.Z_PK, m.ZTEXT, m.ZMESSAGEDATE, m.ZISFROMME, s.Z_PK, COALESCE(s.ZPARTNERNAME, '')
    FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON m.ZCHATSESSION = s.Z_PK
    WHERE m.ZTEXT IS NOT NULL AND m.ZTEXT != ''
    """

func rows(_ raw: [[Any?]]) -> [Row] {
    raw.map {
        Row(
            pk: $0[0] as? Int64 ?? 0, text: $0[1] as? String ?? "", date: number($0[2]),
            fromMe: ($0[3] as? Int64 ?? 0) == 1, chatId: $0[4] as? Int64 ?? 0,
            chatName: $0[5] as? String ?? "")
    }
}

// Palabras de fecha u hora en español: solo esos mensajes salen de la Mac.
let datePattern = try! NSRegularExpression(
    pattern: """
        \\b(hoy|mañana|pasado mañana|lunes|martes|miércoles|miercoles|jueves|viernes|sábado|\
        sabado|domingo|próxim[oa]|proxim[oa]|semana que entra|fin de semana|enero|febrero|\
        marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|\
        a las \\d|\\d{1,2}:\\d{2}|\\d{1,2}\\s?(am|pm|hrs?)|\\d{1,2}/\\d{1,2}|de la (mañana|tarde|noche))\\b
        """, options: [.caseInsensitive])

func mentionsDate(_ text: String) -> Bool {
    datePattern.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil
}

let iso = ISO8601DateFormatter()

func json(_ row: Row, context: Bool) -> [String: Any] {
    [
        "id": String(row.pk), "chat": String(row.chatName.isEmpty ? "chat \(row.chatId)" : row.chatName).prefix(120).description,
        "de_mi": row.fromMe, "texto": String(row.text.prefix(4000)),
        "fecha": iso.string(from: Date(timeIntervalSince1970: row.date + appleEpoch)),
        "contexto": context,
    ]
}

// --- Programa ---

let checkOnly = CommandLine.arguments.contains("--revisar")
guard let configData = try? Data(contentsOf: configURL),
    let config = try? JSONDecoder().decode(Config.self, from: configData)
else { fail("Falta ~/.jarvis/whatsapp.json con la URL de JARVIS.") }
let excluded = Set((config.excluir ?? []).map { $0.lowercased() })

let snapshot = snapshotDatabase()
defer { try? FileManager.default.removeItem(at: snapshot) }
var db: OpaquePointer?
guard
    sqlite3_open_v2(
        snapshot.appendingPathComponent("ChatStorage.sqlite").path, &db, SQLITE_OPEN_READWRITE,
        nil) == SQLITE_OK
else { fail("No pude abrir la copia del archivo de WhatsApp.") }
defer { sqlite3_close(db) }

if checkOnly {
    let tables = query(db, "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ZWA%'")
    let count = query(db, "SELECT COUNT(*) FROM ZWAMESSAGE")
    let chats = query(db, "SELECT COUNT(*) FROM ZWACHATSESSION")
    print("Tablas: \(tables.compactMap { $0[0] as? String }.joined(separator: ", "))")
    print("Mensajes: \(count.first?[0] ?? 0). Chats: \(chats.first?[0] ?? 0).")
    print("El archivo se puede leer. No se mandó nada.")
    exit(0)
}

var state = (try? JSONDecoder().decode(State.self, from: Data(contentsOf: stateURL)))
if state == nil {
    // Primera vez: empieza con las últimas 24 horas.
    let since = Date().timeIntervalSince1970 - appleEpoch - 86_400
    let first = query(db, "SELECT COALESCE(MIN(Z_PK), 0) - 1 FROM ZWAMESSAGE WHERE ZMESSAGEDATE >= \(since)")
    state = State(ultimo: first.first?[0] as? Int64 ?? 0)
}

let fresh = rows(
    query(db, messageSQL + " AND m.Z_PK > ? ORDER BY m.Z_PK LIMIT 3000") {
        sqlite3_bind_int64($0, 1, state!.ultimo)
    }
).filter { !excluded.contains($0.chatName.lowercased()) }

var outgoing: [[String: Any]] = []
var sentIds = Set<Int64>()
for row in fresh where mentionsDate(row.text) {
    let before = rows(
        query(db, messageSQL + " AND s.Z_PK = ? AND m.Z_PK < ? ORDER BY m.Z_PK DESC LIMIT \(contextBefore)") {
            sqlite3_bind_int64($0, 1, row.chatId)
            sqlite3_bind_int64($0, 2, row.pk)
        })
    let after = fresh.filter { $0.chatId == row.chatId && $0.pk > row.pk }.prefix(contextAfter)
    for item in before.reversed() + [row] + after where !sentIds.contains(item.pk) {
        sentIds.insert(item.pk)
        outgoing.append(json(item, context: item.pk != row.pk && item.pk <= state!.ultimo))
    }
}

let newest = fresh.map(\.pk).max() ?? state!.ultimo
if !outgoing.isEmpty {
    var request = URLRequest(url: URL(string: config.url + "/whatsapp/mensajes")!)
    request.httpMethod = "POST"
    request.timeoutInterval = 170
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("Bearer \(keychainToken())", forHTTPHeaderField: "Authorization")
    request.httpBody = try! JSONSerialization.data(withJSONObject: ["mensajes": Array(outgoing.prefix(300))])
    let done = DispatchSemaphore(value: 0)
    var status = 0
    URLSession.shared.dataTask(with: request) { _, response, _ in
        status = (response as? HTTPURLResponse)?.statusCode ?? 0
        done.signal()
    }.resume()
    done.wait()
    guard status == 200 else { fail("JARVIS respondió \(status); lo intento en la siguiente corrida.") }
}

try? FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
try! JSONEncoder().encode(State(ultimo: newest)).write(to: stateURL)
print("Revisados \(fresh.count) mensajes nuevos; mandé \(outgoing.count) con posibles citas.")
