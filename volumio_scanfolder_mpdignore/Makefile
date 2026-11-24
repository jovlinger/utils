# Fast tests for Volumio scanFolder .mpdignore honor (Node + patch helper).
# Root `make test` includes this dir via the */Makefile wildcard.

.PHONY: binlinks test all-tests

binlinks:
	@:

test:
	node test_mpdignore_exclude_tree.js
	node test_mpdignore_ancestor_seed.js
	node test_mpdignore_album_local_cycle.js
	node test_mpdignore_clear_safe.js
	node test_mpdignore_cross_album_fanout.js
	node test_resolve_tags_leaf.js
	node test_enqueue_prefixes.js
	node test_mpdignore_features.js
	python3 -m unittest test_apply_to_index.py test_apply_lsinfo_tags_resolve.py

all-tests: test
