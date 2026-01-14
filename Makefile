.PHONY: test format

test:
	python -m unittest discover -s app/tests

format:
	dev/format_python.sh
