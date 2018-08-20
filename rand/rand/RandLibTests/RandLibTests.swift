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
        
        // mutate the rnd function to be deterministic
        rnd = {(range: CountableRange<Int>) -> Int in
            return range.upperBound - 1
        }
        
        var rdp = ReadDataProtocolMock(str: "hello")
        //var ins = Inputs(filehandles: [FileHandle]())
    }
}
