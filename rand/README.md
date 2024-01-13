When picking up a new language, I like to have a somewhat standard test program:

**randomize the lines from std-in or a file**.

The implicit restriction is that we cannot just read them into memory and output them randomly. 

The solution I go for is to pre-read a buffer of 1000 ish, and when that is full or the stream is empty, 
then start selecting one for output and reading into the buffer as we have space.

Here we find (as of writing): Go, python (2 I think), and swift.
