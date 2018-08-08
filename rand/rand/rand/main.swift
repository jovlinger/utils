//
//  main.swift
//  rand
//
//  Created by Johan Ovlinger on 8/7/18.
//  Copyright © 2018 Johan Ovlinger. All rights reserved.
//

import Foundation

class Inputs {
    var files : [InputStream]
    init(filenames : [String]) {
        files = filenames.map({(filename : String) in open(filename)})
    }
}
