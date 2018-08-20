//
//  Randomize.swift
//
//  Created by Johan on 8/17/18.
//  Copyright © 2018 Johan Ovlinger. All rights reserved.
//

import Foundation

// Varible for unit test support.
var rnd = { (range: CountableRange<Int>) -> Int in
        return range.lowerBound + Int(arc4random_uniform(UInt32(range.upperBound - range.lowerBound)))
}

public enum Option {
    case bufferSize(Int)
}

// These support testing. We can now create a ReadDataMock class in our tests and use that.
public protocol ReadDataProtocol { // Aka a go interface
    func readData(ofLength: Int) -> Data
    func closeFile() -> Void
}
public protocol WriteDataProtocol {
    func write(_: Data) -> Void
    func closeFile() -> Void
}
extension FileHandle : ReadDataProtocol, WriteDataProtocol {
} // In swift we explicitly declare interface conformance

struct Input {
    let readSize = 1024
    var filehandle : ReadDataProtocol!
    var buffer : Data
    let delim = "\n".data(using: .utf8)! // why is it wrong to say String.Encoding.utf8 ?
    
    init(filehandle : ReadDataProtocol) {
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
                // EOF or read error -> output last line if any.
                break
            }
        }
        close()
        if buffer.count > 0 {
            // Buffer contains last line in file (not terminated by delimiter).
            let line = String(data: buffer, encoding: .utf8)! + "\n"
            buffer.count = 0
            return line
        }
        // Input ended with a delimiter, so we are done.
        return nil
    }
}

struct Inputs {
    var inputs : [Input]
    var i = -1 // Least bad way to read from first input file first. 
    
    init(filehandles : [ReadDataProtocol]) {
        inputs = filehandles.map({fh in return Input(filehandle: fh)})
    }
    
    // Return next input line, or nil if all inputs are EOF.
    mutating func line() -> String? {
        while inputs.count > 0 {
            i = (i + 1) % inputs.count
            if let nl = inputs[i].nextLine() {
                print("DEBUG: input \(i) had line '\(nl)'")
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
    
    init(inputs : Inputs, cap: Int) {
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
                let idx = rnd(lines.startIndex ..< lines.endIndex)
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
        if line != nil && (lines.count == cap) && (rnd(0 ..< cap) == 0) {
            // output next line directly
            return (line, true)
        }
        let ret = procline(line: line)
        return (ret, line != nil || ret != nil)
    }
}

public func randomize(opts: [Option], ins: [ReadDataProtocol], out: WriteDataProtocol) {
    var bufferSize = 1024
    for opt in opts {
        switch opt {
        case let .bufferSize(n): bufferSize = n
        }
    }
    var buffer = Buffer(inputs: Inputs(filehandles: ins), cap: bufferSize)
    while true {
        let (line, more) = buffer.choose()
        if !more { break }
        if let theline = line {
            out.write(theline.data(using: .utf8)!)
        }
    }
    out.closeFile()
}
