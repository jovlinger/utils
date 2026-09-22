// nlce-embed: a long-lived sidecar exposing Apple's on-device
// NLContextualEmbedding over stdin/stdout as JSON lines. Driven by
// todo_embed_apple.AppleEmbedder. macOS 14+ only.
//
// Protocol -- one JSON object per line, both directions:
//   ->  {"op": "info"}                  <-  {"model": str, "revision": int, "dim": int}
//   ->  {"op": "embed", "text": "..."}  <-  {"vector": [double, ...]}
//   (any request)                       <-  {"error": "..."}   on failure
//
// The vector is the mean of the model's per-token vectors, L2-normalized. If the
// pooling or normalization here changes, bump _PROCESSING_VERSION in
// todo_embed_apple.py so old vectors are not compared against new ones.

import Foundation
import NaturalLanguage

// Emit one JSON object per line, then flush so the caller's readline unblocks.
func emit(_ obj: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: obj),
       let s = String(data: data, encoding: .utf8) {
        print(s)
    } else {
        print("{\"error\": \"failed to encode response\"}")
    }
    fflush(stdout)
}

func fail(_ msg: String) {
    emit(["error": msg])
}

// Pinned model: the English contextual embedding. Whatever this resolves to, we
// report its identifier + revision on "info" so the Python fingerprint records
// the exact space these vectors live in.
let language: NLLanguage = .english

guard let embedding = NLContextualEmbedding(language: language) else {
    fail("no NLContextualEmbedding model for \(language.rawValue)")
    exit(1)
}

// Ensure on-device assets are present; this may download them on first use.
if !embedding.hasAvailableAssets {
    let sem = DispatchSemaphore(value: 0)
    var assetError: String?
    embedding.requestAssets { result, error in
        if result != .available {
            assetError = "assets unavailable (\(result)): \(error?.localizedDescription ?? "no detail")"
        }
        sem.signal()
    }
    sem.wait()
    if let message = assetError {
        fail(message)
        exit(1)
    }
}

do {
    try embedding.load()
} catch {
    fail("model load failed: \(error.localizedDescription)")
    exit(1)
}

let dimension = embedding.dimension

// Mean-pool the per-token vectors, then L2-normalize. Returns nil when the text
// yields no usable tokens.
func meanPooled(_ text: String) -> [Double]? {
    if text.isEmpty { return nil }
    guard let result = try? embedding.embeddingResult(for: text, language: language) else {
        return nil
    }
    var sum = [Double](repeating: 0.0, count: dimension)
    var count = 0
    result.enumerateTokenVectors(in: text.startIndex..<text.endIndex) { vector, _ in
        if vector.count == dimension {
            for i in 0..<dimension { sum[i] += vector[i] }
            count += 1
        }
        return true
    }
    if count == 0 { return nil }
    for i in 0..<dimension { sum[i] /= Double(count) }
    var norm = 0.0
    for v in sum { norm += v * v }
    norm = norm.squareRoot()
    if norm > 0 {
        for i in 0..<dimension { sum[i] /= norm }
    }
    return sum
}

// Request loop: one JSON object per input line until stdin closes.
while let line = readLine(strippingNewline: true) {
    if line.isEmpty { continue }
    guard let data = line.data(using: .utf8),
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          let op = obj["op"] as? String else {
        fail("malformed request")
        continue
    }
    switch op {
    case "info":
        emit([
            "model": embedding.modelIdentifier,
            "revision": embedding.revision,
            "dim": dimension,
        ])
    case "embed":
        guard let text = obj["text"] as? String else {
            fail("embed request missing text")
            continue
        }
        // Empty/untokenizable text still returns a well-formed zero vector so the
        // caller always gets a comparable, correct-width result.
        let vec = meanPooled(text) ?? [Double](repeating: 0.0, count: dimension)
        emit(["vector": vec])
    default:
        fail("unknown op: \(op)")
    }
}
