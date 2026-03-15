.PHONY: test format

test:
	cd app/tests && python3 -m unittest discover -p 'test_*.py'

format:
	dev/format_python.sh
