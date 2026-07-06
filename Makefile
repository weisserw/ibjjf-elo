.PHONY: test test-ocr format

OCR_TESTS = \
	test_livestream_frame_text_scan

NON_OCR_TESTS = $(shell cd app/tests && find . -maxdepth 1 -name 'test_*.py' \
	! -name 'test_livestream_frame_text_scan.py' \
	-exec basename {} .py \; | sort)

test:
	cd app/tests && python3 -m unittest $(NON_OCR_TESTS)

test-ocr:
	cd app/tests && RUN_OCR_TESTS=1 python3 -m unittest $(OCR_TESTS)

format:
	dev/format_python.sh
