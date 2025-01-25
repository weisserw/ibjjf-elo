from progress.bar import Bar as ProgressBar

# custom progress bar that can log to a file in non-tty environments


class Bar(ProgressBar):

    def writeln(self, line):
        if not self.no_tty:
            super().writeln(line)
        elif line.strip():
            if self.file and self.is_tty():
                width = len(line)
                if width < self._max_width:
                    line += " " * (self._max_width - width)
                else:
                    self._max_width = width
                print(line + "\n", end="", file=self.file)
                self.file.flush()

    def update(self):
        if not self.no_tty:
            super().update()
        else:
            if getattr(self, "last_percent", None) is not None and round(
                self.last_percent
            ) == round(self.percent):
                return
            self.last_percent = self.percent

            super().update()

    def finish(self):
        if not self.no_tty:
            super().finish()
