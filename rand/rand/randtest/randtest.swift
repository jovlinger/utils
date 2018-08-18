//
//  randtest.swift
//  randtest
//
//  Created by Johan on 8/17/18.
//  Copyright © 2018 Johan Ovlinger. All rights reserved.
//

//import Foundation
import XCTest
@testable import rand

class randtest: XCTestCase {
    
    override func setUp() {
        super.setUp()
        // Put setup code here. This method is called before the invocation of each test method in the class.
    }
    
    override func tearDown() {
        // Put teardown code here. This method is called after the invocation of each test method in the class.
        super.tearDown()
    }
    
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

        var i = Input()
        //var ins = Inputs(filehandles: [FileHandle]())
        
    }
    
    func testPerformanceExample() {
        // This is an example of a performance test case.
        self.measure {
            // Put the code you want to measure the time of here.
        }
    }
    
}
