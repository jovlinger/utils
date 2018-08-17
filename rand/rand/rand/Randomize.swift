//
//  Randomize.swift
//  rand
//
//  Created by Johan on 8/17/18.
//  Copyright © 2018 Johan Ovlinger. All rights reserved.
//

import Foundation

import Foundation

extension Int {
    static func random(in range: CountableRange<Int>) -> Int {
        return range.lowerBound + Int(arc4random_uniform(UInt32(range.upperBound - range.lowerBound)))
    }
}

struct Input {
    let readSize = 1024
    var filehandle : FileHandle!
    var buffer : Data
    let delim = "\n".data(using: .utf8)! // why is it wrong to say String.Encoding.utf8 ?
    
    init(filehandle : FileHandle) {
        buffer = Data(capacity: readSize)
        self.filehandle = filehandle
    }
    
    mutating func close() {
        if filehandle == nil {
            return
        }
        filehandle.closeFile()
        filehandle = nil
    }
    
    mutating func nextLine() -> String? {
        // Pretty much copied from https://gist.github.com/klgraham/6fe11ed1e3fe075f5ffc8b7ca350bce4
        // nil implies EOF
        
        while filehandle != nil {
            if let range = buffer.range(of: delim) {
                // We have a delim, so clip and return upto there
                // upperBound -> include delim, else lowerBound -> exclude
                let line = String(data: buffer.subdata(in: 0..<range.upperBound), encoding: .utf8)
                buffer.removeSubrange(0..<range.upperBound)
                return line
            }
            // No delim, so read some more
            let tmpData = filehandle.readData(ofLength: readSize)
            if tmpData.count > 0 {
                buffer.append(tmpData)
            } else {
                close()
                // EOF or read error.
                if buffer.count > 0 {
                    // Buffer contains last line in file (not terminated by delimiter).
                    let line = String(data: buffer, encoding: .utf8)! + "\n"
                    buffer.count = 0
                    return line
                }
            }
        }
        return nil
    }
}

struct Inputs {
    var inputs : [Input]
    var i = 0
    
    init(filehandles : [FileHandle]) {
        inputs = filehandles.map({fh in return Input(filehandle: fh)})
    }
    
    // Return next input line, or nil if all inputs are EOF.
    mutating func line() -> String? {
        while inputs.count > 0 {
            i = (i + 1) % inputs.count
            if let nl = inputs[i].nextLine() {
                return nl
            } else {
                inputs.remove(at: i)
            }
        }
        return nil
    }
}

struct Buffer {
    var lines = [String]()
    var count = 0
    var inputs : Inputs
    let cap : Int
    
    init(inputs : Inputs, cap :Int = 1000) {
        self.inputs = inputs
        self.cap = cap
    }
    
    mutating func procline(line: String?) -> String? {
        if let theline = line {
            lines.append(theline)
        }
        if line == nil || lines.count > cap {
            if lines.endIndex > 0 {
                let last = lines.endIndex-1
                let idx = Int.random(in: lines.startIndex ..< lines.endIndex)
                let l = lines[idx]
                lines[idx] = lines[last]
                lines[last] = l
            }
            return lines.popLast()
        }
        return nil
    }
    
    // returns String?, more-to-come
    mutating func choose() -> (String?, Bool) {
        count += 1
        let line = inputs.line()
        if line != nil && (lines.count == cap) && (Int.random(in: 0 ..< cap) == 0) {
            // output next line directly
            return (line, true)
        }
        let ret = procline(line: line)
        return (ret, line != nil || ret != nil)
    }
}

func randomize(ins: [FileHandle], out: FileHandle) {
    var buffer = Buffer(inputs: Inputs(filehandles: ins))
    while true {
        let (line, more) = buffer.choose()
        if !more { break }
        if let theline = line {
            out.write(theline.data(using: .utf8)!)
        }
    }
}
