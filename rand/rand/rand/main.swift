//
//  main.swift
//  rand
//
//  Created by Johan Ovlinger on 8/7/18.
//  Copyright © 2018 Johan Ovlinger. All rights reserved.
//

import Foundation
import RandLib

func parseArgs(args: [String]) -> ([String], [Option]) {
    var idx = 1
    var opts = [Option]()
    while idx < args.endIndex {
        let arg = args[idx]
        switch arg {
        case "-b":
            idx += 1
            opts.append(.bufferSize(Int(args[idx])!))
        default:
            if arg.hasPrefix("-") {
                print("Unable to parse option \(arg)")
            } else {
                // done parsing options
                break
            }
        }
        idx += 1
    }
    return (Array(args[idx...]), opts)
}

// Make fake filehandle for testing
func main(opts: [Option], paths : [String], stdin: FileHandle, stdout: FileHandle) {
    var filehandles = paths.map({ FileHandle(forReadingAtPath: $0)! })
    filehandles.append(stdin)
    randomize(opts: opts, ins: filehandles, out: stdout)
    /*
    // FIXME debug
    rnd = {(range: CountableRange<Int>) -> Int in
        let r = rnd(range)
        print("ramdom: \(r)")
        return r
    }
    */
}

let (filePaths, opts) = parseArgs(args: CommandLine.arguments)
main(opts: opts, paths: filePaths, stdin: FileHandle.standardInput, stdout: FileHandle.standardOutput)
