//
//  RandLibTests.swift
//  RandLibTests
//
//  Created by Johan on 8/18/18.
//  Copyright © 2018 Johan Ovlinger. All rights reserved.
//

import XCTest
@testable import RandLib

class ReadDataProtocolMock : ReadDataProtocol {
    var data : Data
    init(str: String) {
        data = str.data(using: .utf8)!
    }
    func readData(ofLength: Int) -> Data {
        return data.subdata(in: 0 ..< ofLength)
    }
    func closeFile() -> Void {}
}

class RandLibTests: XCTestCase {
    func testExample() {
        // This is an example of a functional test case.
        // Use XCTAssert and related functions to verify your tests produce the correct results.
        
        /*
         rnd = {(range: CountableRange<Int>) -> Int in
         return range.upperBound - 1
         }
         */
        // Create a few fileHandle-ish objects to read from, and an output one to write to.
        let inputs = [[1, 2, 3], [4], [5, 6, 7, 8, 9]].map({"\($0)"})
        
        var rdp = ReadDataProtocolMock(str: "hello")
        //var ins = Inputs(filehandles: [FileHandle]())
    }
}
