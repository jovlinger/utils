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
        let end = data.count < ofLength ? data.count :ofLength
        let out = data.subdata(in: 0 ..< end)
        data = data.subdata(in: end ..< data.count)
        return out
    }
    func closeFile() {}
}
class WriteDataProtocolMock : WriteDataProtocol {
    var strs: [String] = []
    func write(_ data: Data) {
        strs.append(String(data: data, encoding: .utf8)!)
    }
    func closeFile() {}
}

class RandLibTests: XCTestCase {
    func testRandomize() {
        // This is an example of a functional test case.
        // Use XCTAssert and related functions to verify your tests produce the correct results.
        
        // mutate the rnd function to be deterministic
        rnd = {(range: CountableRange<Int>) -> Int in return range.endIndex - 1 }
        
        let rpds = ["one\ntwo\nthree\nfour\nfive\n\n", "uno\ndos", "ett\ntva\ntre", "un"].map({ReadDataProtocolMock(str: $0)})
        
        let wdp = WriteDataProtocolMock()
        randomize(opts: [], ins: rpds, out: wdp)
        XCTAssertEqual(wdp.strs,
                       ["\n", "five\n", "four\n", "tre\n", "three\n", "tva\n", "dos\n", "two\n", "un\n", "ett\n", "uno\n", "one\n"])
    }
    func testBufferSize() {
        // This is an example of a functional test case.
        // Use XCTAssert and related functions to verify your tests produce the correct results.
        
        // mutate the rnd function to be deterministic
        rnd = {(range: CountableRange<Int>) -> Int in return range.endIndex - 1 }
        
        let rpds = ["one\ntwo\nthree\nfour\nfive\n\n", "uno\ndos", "ett\ntva\ntre", "un"].map({ReadDataProtocolMock(str: $0)})
        
        let wdp = WriteDataProtocolMock()
        randomize(opts: [.bufferSize(3)], ins: rpds, out: wdp)
        XCTAssertEqual(wdp.strs,
                       ["un\n", "two\n", "dos\n", "tva\n", "three\n", "tre\n", "four\n", "five\n", "\n", "ett\n", "uno\n", "one\n"])
    }
}
