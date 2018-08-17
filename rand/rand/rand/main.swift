//
//  main.swift
//  rand
//
//  Created by Johan Ovlinger on 8/7/18.
//  Copyright © 2018 Johan Ovlinger. All rights reserved.
//

import Foundation

// Make fake filehandle for testing
func main(paths : [String], stdin: FileHandle, stdout: FileHandle) {
    var filehandles = paths.map({ FileHandle(forReadingAtPath: $0)! })
    filehandles.append(stdin)
    randomize(ins: filehandles, out: stdout)
}

enum Option {
    
}

func parseArgs(args: [String]) -> ([String], [Option]) {
    return (Array(args[1...]), [Option]())
}

let (filePaths, opts) = parseArgs(args: CommandLine.arguments)
main(paths: filePaths, stdin: FileHandle.standardInput, stdout: FileHandle.standardOutput)
