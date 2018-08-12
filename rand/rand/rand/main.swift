//
//  main.swift
//  rand
//
//  Created by Johan Ovlinger on 8/7/18.
//  Copyright © 2018 Johan Ovlinger. All rights reserved.
//

import Foundation

extension Int {
    static func random(in range: CountableRange<Int>) -> Int {
        return range.lowerBound + Int(arc4random_uniform(UInt32(range.upperBound - range.lowerBound)))
    }
}

struct Inputs {
    var files : [InputStream]
    init(filenames : [String]) {
        // files = filenames.map({(filename : String) in open(filename)})
    }

    // Return next input line, or nil if all inputs are EOF.
    mutating func line() -> String? {

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
    // If line && full : return random existing entry, replacing with line.
    // if line && !full : append line to buffer
    // if !line: return random entry.
    mutating func procline(line: String?) -> String? {
        if let theline = line {
            lines.append(theline)
        }
        var idx = Int.random(in: 0 ..< cap)
        var l = lines[idx]
        lines[idx] = lines[-1]
        lines[-1] = l
        if line == nil || lines.count > cap {
            return lines.popLast()
        }
        return nil
    }
    
    mutating func choose() -> String? {
        count += 1
        var line = inputs.line()
        if (lines.count == cap) && (Int.random(in: 0 ..< cap) == 0) {
            // output next line directly
            return line
        }
        return procline(line: line)
    }
}
