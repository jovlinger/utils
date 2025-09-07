Merkle FUSE
===========

# TL;DR
this is a FUSE filesystem, backed by an n-ary merkle tree.
The presented file system looks like a normal r/w filesystem, eventually covering all actions available to NFS or CIFS. 
The directory structure will be stored directly in the merkle tree, whose nodes are immutable.
Thus, every mutation will result in new nodes, percolating to the root.
The filesytem's state is uniquely and unambigiously identified by `(root node entry, map of hash -> file)`, where:
- The **map of hash -> file** is stored as individual files in the hosting filesystem under `./data/<hash>`, where `<hash>` is the 64-character hex SHA256 hash
- The **root node entry** is a short text file stored in the hosting filesystem under filename `./root_<RFC3339>.txt` containing the SHA256 hash of the root directory node
- The root node entry file serves as the single source of truth for the current filesystem state
- To read the filesystem, you first read the root node entry to get the root hash, then use that hash to look up the root directory in the data store  



# Details of file system

The system consists of nodes, which are either a raw file or file containing a json directory listing. 
All files are stored under the SHA256 hash of its contents, represented as 64 char hex, in the `./data/` directory of the hosting filesystem. The physical path for a file with hash `abc123...` would be `./data/abc123...` (no file extension). 
That the contents hash and filename match is verified before and after writing, and after reading.
Mismatches cause critical errors in the logs and non-recoverable errors in the response.
- **Raw File**: any file: a .pdf, .mp4 movie, .py, or anything. 
- **JSON Directory Listing**: a json object. 
    - Each key/value represents a entry in the directory. 
    - the key is the name of the file, as it would appear as a component in the path (no '/')
    - the value is an object with metadata for entry. all are mandatory for writing, optional for reading (sensible defaults)
        - sha256: the sha256 the physical file is stored under
        - ownership : object { "U" : string, "G": [list of string] **Empty ok**}
        - auth : object (key: string 'U' / 'G' / 'O', value: string subset of "rwx")  
        - ctime : string rfc3339 with E-6 sec (creation time - this is the only timestamp we track)

**Metadata Defaults for Reading:**
- If ownership missing: U="root", G=[]
- If auth missing: U="rwx", G="rwx", O="rwx" 
- If ctime missing: use current time when reading
- For FUSE operations requiring mtime/atime: return ctime value

(We cannot store all hashed files under `./data`. Filesystems are not optimized for having many thousand files in one directory.  Instead the physical path will be `./data/<hash>[:prefix]/<hash>`, where prefix is configurable (default: 2). This physical location of any stored file will not be visible in any hashes stored in directory listings)

## Operations

### Read

to read a path, we will open the root file as per the root node entry.  
We will strip the leading '/' if exists. 
Then iteratively look up the path components, reading the next file for each.  

If a non-leaf file is not a valid json directory listing, that is an error. 
For the leaf path: we assume it is a file and return its contents. If it is actually a directory (JSON listing), we return the JSON content anyway. In Unix reading a directory returns an error, but we cannot distinguish between a file that happens to contain JSON and an actual directory listing, so we return the content regardless. 

### Writes

- recursively walk target path. Assert we find a directory there.  
    - No files will ever be created automatically. All creation must be explicit. just like a unix FS, the user must first create `/a`, `/a/b`, `/a/b/c` in order to write `/a/b/c/file.txt`. 
- write the file, with sha256 checks before and after. 
- If success, insert an entry into the json directory listing file, overwriting the old file entry if there was one.
- write the updated json directory listing into the filesystem, and unrecurse (return) back into the parent folder. 
- continue returning until we have a new root node entry, whcih we write into `root.<rfc3339>`.

**Error Handling:** For any failed write operation, including a failed SHA256, match move the file to /tmp (if debug enabled) or delete it, then return an error to the caller.


### Deletes

simlar to write, but with entry just removed

### Others (tbd)
 (Read, Write, Seek, Delete, Makedir, Listdir, Chmod, Getattr, Readdir, Mknod, Symlink, Readlink, Rename, Truncate, Utimens, Chown). 


### GC

to be implemented later. The system will not receive rapid updates that will necessiate this for now.

## Initial Filesystem State

The filesystem starts with an empty root directory represented as an empty JSON object `{}`. This empty JSON object is stored as a file in the data directory, and its SHA256 hash becomes the initial root hash. The `data_directory` (default: `./data`) must exist before starting the filesystem - the system will refuse to start if it does not exist.

## Known Flaws & Limitations

### Concurrency
- **Current Limitation:** Zero control. YOLO.
- **Immediate Enhancement** All write operations are serialized. Concurrent writes are not supported in this version implementation.
- **Future Enhancement:** Concurrent writes will be supported in a future version, requiring behind-the-scenes merging of directory listings. This is not needed for MVP or beta versions.
- **Impact:** Multiple processes writing simultaneously YOLO **will** result in data loss (last-write-wins).  We will fix this rapidly.

## System setup


The FUSE system will run as an auto-restarted server in user space. 
It will log to the standard syslog, logging at INFO level initially, but if a critical error such as a mismatch occurs it will temporarily (5 mins, configurable) switch to most finegrained level (DEBUG in Python).


The implementation will be pure python3, with pipenv and simple requirements.txt file 

black and pylint will enforce code health.

All development will be pytest-driven:
- unit tests. These will mock actual file-system operations
    1. A test is written for each basic unit of functionality listed in Section Operations above.
    2. that function is implemented to satisfy the test
    3. Once all basic functions are finished, the we will start to hook up the FUSE api to these functions, again tests first.
- integration tests. These will have fixtures to set up a local root for tests in /tmp (and will clean up if tests pass). This does not mock the operations.
    1. We will run a sequence of operations, and check that the state in the /tmp test area is correct.
- end-to-end tests (manual via Makefile for now)
    1. we will load the FUSE system into the machine and run the integration test suite again, but this time via the kernel.

## Filesystem Limits (Constants)

- `MAX_PATH_LENGTH`: 4096 characters (standard Unix limit)
- `MAX_FILENAME_LENGTH`: 255 characters (standard Unix limit) 
- `MAX_DIRECTORY_ENTRIES`: 10000 entries per directory
- `MAX_JSON_SIZE`: 1MB for directory listing files
- `MAX_FILE_SIZE`: 1GB (configurable via config) 

Build and test will be controlled by a Makefile

## Config

will be a single json file stored in the idiomatic system service folder (`/etc/merklefuse/config.json` or `~/.config/merklefuse/config.json` for user mode).

Configuration options:
* `debug`: boolean (default: false) - whether to keep failed files in /tmp instead of deleting them
* `log_level`: string (default: "INFO") - initial logging level ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
* `critical_debug_duration`: integer (default: 300) - seconds to maintain DEBUG level logging after a critical error
* `data_directory`: string (default: "./data") - path to the directory storing hash-indexed files
* `root_file_prefix`: string (default: "root_") - prefix for root node entry files
* `max_file_size`: integer (default: 1073741824) - maximum file size in bytes (1GB default)
* `enable_atime`: boolean (default: false) - whether to track access times (performance impact)
* `cache_size`: integer (default: 1000) - number of directory entries to cache in memory (TBD - post MVP)
* `directory_organize_prefixlen`: integer (default: 2) - prefix length of each hash to sort files into `./data/<prefix>/<hash>` folders

# FUSE API entry points

**Library Choice: mfusepy** - We will use `mfusepy` as our Python FUSE library. Alternative considered: `refuse` (more Pythonic but limited platform support).

## mfusepy Programming API

### Installation
```bash
pip install mfusepy
```

### Required Operations to Implement

Our filesystem class must inherit from `mfusepy.Operations` and implement these methods:

**Core File Operations:**
- `getattr(self, path, fh=None)` - Get file/directory attributes (mode, size, timestamps, etc.)
- `readdir(self, path, fh)` - List directory contents (returns list of filenames)
- `open(self, path, flags)` - Open a file (returns file handle)
- `read(self, path, size, offset, fh)` - Read data from file
- `write(self, path, data, offset, fh)` - Write data to file
- `truncate(self, path, length)` - Resize file
- `unlink(self, path)` - Delete a file
- `mkdir(self, path, mode)` - Create directory
- `rmdir(self, path)` - Remove directory
- `rename(self, old, new)` - Move/rename file or directory

**Permission & Metadata Operations:**
- `chmod(self, path, mode)` - Change file permissions
- `chown(self, path, uid, gid)` - Change file ownership
- `utimens(self, path, times=None)` - Update file timestamps

### Basic Implementation Structure

```python
from mfusepy import FUSE, Operations
import os
import errno

class MerkleFuseFS(Operations):
    def __init__(self, config):
        # Initialize our Merkle tree filesystem
        self.config = config
        # ... setup data structures
        
    def getattr(self, path, fh=None):
        # Return file attributes from our Merkle tree
        # Must return dict with st_mode, st_size, st_ctime, etc.
        
    def readdir(self, path, fh):
        # Return directory listing from JSON directory node
        # Must return ['.', '..'] + list of filenames
        
    def read(self, path, size, offset, fh):
        # Read file content from our hash-indexed storage
        # Return bytes data
        
    def write(self, path, data, offset, fh):
        # Write data, update Merkle tree, return bytes written
        
    # ... implement other required methods

# Mount the filesystem
if __name__ == '__main__':
    fuse = FUSE(MerkleFuseFS(config), mountpoint, foreground=True)
```

### Implementation Priority

**Core Operations (MVP):**
- `getattr(self, path, fh=None)` - Get file/directory attributes
- `open(self, path, flags)` - Open a file (returns file handle)
- `read(self, path, size, offset, fh)` - Read data from file
- `write(self, path, data, offset, fh)` - Write data to file
- `unlink(self, path)` - Delete a file (maybe - depends on complexity)

**Secondary Operations (implemented in terms of core):**
- `rename(self, old, new)` - Read old file, write to new path, unlink old
- `truncate(self, path, length)` - Read file, truncate data, write back
- `mkdir(self, path, mode)` - Create empty directory (JSON `{}`)
- `rmdir(self, path)` - Remove directory (unlink if empty)
- `readdir(self, path, fh)` - Read directory JSON, return keys
- `chmod(self, path, mode)` - Read metadata, update, write back
- `chown(self, path, uid, gid)` - Read metadata, update, write back
- `utimens(self, path, times=None)` - Read metadata, update, write back

### File Handle Design

**File Handle Structure (ephemeral in-memory):**
```python
class FileHandle:
    def __init__(self, path: str, flags: int, mode: str):
        self.path = path          # Full path to file
        self.flags = flags        # Open flags (O_RDONLY, O_WRONLY, O_RDWR, etc.)
        self.mode = mode          # 'r', 'w', 'a', etc.
        self.position = 0         # Current read/write position
        self.file_hash = None     # SHA256 hash of the file content
        # self.parent_hash = None   # parent_directory_hash to allow consistent reads ? 
        self.is_directory = False # Whether this is a directory handle
```

**File Handle Management:**
- `open()` creates a new `FileHandle` object, stores it in a dict keyed by handle ID
- Handle ID is a simple incrementing integer starting from 1
- `read()`/`write()` use the handle to track position and file state
- Handles are completely ephemeral - no persistence across filesystem restarts

### Key Implementation Notes

- **Error Handling**: Raise `OSError(errno.ENOENT, ...)` for file not found, etc.
- **File Handles**: `open()` returns a file handle (integer), used in subsequent read/write calls
- **Attributes**: `getattr()` must return a dict with Unix-style file attributes
- **Directory Listing**: `readdir()` must include `'.'` and `'..'` entries
- **Atomic Operations**: Each method should maintain Merkle tree consistency


# Future
