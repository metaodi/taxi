import datetime
import re

from taxi.exceptions import TaxiException
from taxi.utils import date as date_utils


class TextLine(object):
    """
    The TextLine is either a blank line or a comment line.
    """
    def __init__(self, text):
        self._text = text

    def __str__(self):
        return unicode(self).encode('utf-8')

    def __unicode__(self):
        return self.text

    def __repr__(self):
        return '"%s"' % str(self.text)

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value


class EntryLine(TextLine):
    """
    The EntryLine is a line representing a timesheet entry, with an alias, a
    duration and a description. The text attribute allows to keep the original
    formatting of the duration as long as the entry is not changed.
    """
    def __init__(self, alias, duration, description, text=None, ignored=False):
        self._alias = alias
        self.duration = duration
        self.description = description
        self.formatting = None

        # These should normally be always set to False, but can be changed
        # later
        self.commented = False
        self.ignored = ignored

        if text is not None:
            self._text = text

    def __setattr__(self, name, value):
        super(EntryLine, self).__setattr__(name, value)

        if name != '_text':
            self._text = None

    def generate_text(self):
        """
        Return a textual representation of the line.

        An effort is made to preserve the original formatting of the line since
        some OCD people like to have perfectly aligned timesheets.
        """
        formatting = self.formatting

        if not formatting:
            formatting = {
                'width': (None, None),
                'time_format': '%H:%M'
            }

        if isinstance(self.duration, tuple):
            start = (self.duration[0].strftime(formatting['time_format'])
                     if self.duration[0] is not None
                     else '')

            end = (self.duration[1].strftime(formatting['time_format'])
                   if self.duration[1] is not None
                   else '?')

            duration = u'%s-%s' % (start, end)
        else:
            # Remove '.0' if the number doesn't have a decimal part
            duration = str(self.duration).rstrip('0').rstrip('.')

        commented_prefix = '# ' if self.commented else ''
        alias = u'%s?' % self.alias if self.ignored else self.alias

        padding1 = (1 if formatting['width'][0] is None
                    else max(1, formatting['width'][0] - len(alias)))
        padding2 = (1 if formatting['width'][1] is None
                    else max(1, formatting['width'][1] - len(duration)))

        text = (u'{commented}{alias}{padding1}{duration}{padding2}'
                '{description}'.format(commented=commented_prefix,
                                       alias=alias,
                                       padding1=' ' * padding1,
                                       duration=duration,
                                       description=self.description,
                                       padding2=' ' * padding2))

        return text

    @property
    def text(self):
        if self._text is not None:
            return self._text
        else:
            return self.generate_text()

    @property
    def alias(self):
        return self._alias.replace('?', '')

    @alias.setter
    def alias(self, value):
        self._alias = value


class DateLine(TextLine):
    def __init__(self, date, text=None, date_format='%d.%m.%Y'):
        self.date = date

        if text is not None:
            self.text = text
        else:
            self.text = date_utils.unicode_strftime(self.date, date_format)


class TimesheetParser(object):
    """
    Parse a string and transform it into a list of parsed lines (date line,
    entry line, text line). The basic structure is as follows:

    Date line: <date>, where `date` is formatted as dd.mm.yyyy (the `.`
    separator can be replaced by any non-word character)
    Entry line: <alias> <duration> <description>, where `duration` can either
    be expressed as a float/int to mean hours or as a time range (eg.
    `09:00-09:30`, the `:` separator being optional)
    Comment line: any line starting with `#` will be ignored

    For the parsed string to be a valid timesheet, any entry line needs to
    be preceded by at least a date line.
    """
    time_match_re = re.compile(
        r'(?:(\d{1,2}):?(\d{1,2}))?-(?:(?:(\d{1,2}):?(\d{1,2}))|\?)'
    )
    date_match_re = re.compile(r'(\d{1,2})\D(\d{1,2})\D(\d{4}|\d{2})')
    us_date_match_re = re.compile(r'(\d{4})\D(\d{1,2})\D(\d{1,2})')
    formatting_match_re = re.compile(r'([^\s]+\s+)([^\s]+\s+)')

    @classmethod
    def parse(cls, text):
        text = text.strip()
        lines_parser = cls.parser(text.splitlines())

        return [line for line in lines_parser]

    @classmethod
    def parser(cls, lines):
        current_date = None

        for (lineno, line) in enumerate(lines, 1):
            line = line.strip()

            try:
                if len(line) == 0 or line.startswith('#'):
                    yield TextLine(line)
                else:
                    try:
                        date = cls.extract_date(line)
                    except ValueError:
                        if current_date is None:
                            raise ParseError("Entries must be defined inside a"
                                             " date section")

                        yield cls.parse_entry_line(line)
                    else:
                        current_date = date
                        yield DateLine(date, line)
            except ParseError as e:
                e.line_number = lineno
                raise e

    @classmethod
    def parse_entry_line(cls, line):
        split_line = cls.split_line(line)

        alias = split_line[0].replace('?', '')
        time = cls.parse_time(split_line[1])
        description = split_line[2]
        formatting = cls.detect_formatting(line)

        ignored = split_line[0].endswith('?') or split_line[0].startswith('?')

        entry_line = EntryLine(alias, time, description, line, ignored)
        entry_line.formatting = formatting

        return entry_line

    @staticmethod
    def split_line(line):
        split_line = line.split(None, 2)

        if len(split_line) != 3:
            raise ParseError("Couldn't split line into 3 chunks")

        return split_line

    @classmethod
    def detect_formatting(cls, line):
        """
        Extract the width (= number of columns) of the different components of
        the line as well as the time format. The returned data is a dictionary
        with 2 values, 'width' containing a 2-items tuple representing the
        width of the two first components of the line (alias and duration), and
        'time_format' containing the format of the time as a string usable by
        strftime.
        """
        width = re.match(cls.formatting_match_re, line)
        split_line = cls.split_line(line)

        if width and len(width.groups()) == 2:
            width = tuple(len(separator) for separator in width.groups())
        else:
            return None

        time_format = '%H:%M' if ':' in split_line[1] else '%H%M'

        return {
            'width': width,
            'time_format': time_format
        }

    @classmethod
    def parse_time(cls, str_time):
        time = re.match(cls.time_match_re, str_time)
        time_end = None

        # HH:mm-HH:mm syntax found
        if time is not None:
            try:
                # -HH:mm syntax found
                if time.group(1) is None and time.group(2) is None:
                    if time.group(3) is not None and time.group(4) is not None:
                        time_end = datetime.time(
                            int(time.group(3)), int(time.group(4))
                        )

                    total_hours = (None, time_end)
                else:
                    time_start = datetime.time(
                        int(time.group(1)), int(time.group(2))
                    )
                    if time.group(3) is not None and time.group(4) is not None:
                        time_end = datetime.time(
                            int(time.group(3)), int(time.group(4))
                        )
                    total_hours = (time_start, time_end)
            except ValueError as e:
                raise ParseError(e.message)
        else:
            try:
                total_hours = float(str_time)
            except ValueError:
                raise ParseError("The duration must be a float number or a "
                                 "HH:mm string")

        return total_hours

    @classmethod
    def extract_date(cls, line):
        # Try to match dd/mm/yyyy format
        date_matches = re.match(cls.date_match_re, line)

        # If no match, try with yyyy/mm/dd format
        if date_matches is None:
            date_matches = re.match(cls.us_date_match_re, line)

        if date_matches is None:
            raise ValueError("No date could be extracted from the given value")

        # yyyy/mm/dd
        if len(date_matches.group(1)) == 4:
            return datetime.date(int(date_matches.group(1)),
                                 int(date_matches.group(2)),
                                 int(date_matches.group(3)))

        # dd/mm/yy
        if len(date_matches.group(3)) == 2:
            current_year = datetime.date.today().year
            current_millennium = current_year - (current_year % 1000)
            year = current_millennium + int(date_matches.group(3))
        # dd/mm/yyyy
        else:
            year = int(date_matches.group(3))

        return datetime.date(year, int(date_matches.group(2)),
                             int(date_matches.group(1)))


class ParseError(TaxiException):
    def __init__(self, message, line_number=None):
        self.message = message
        self.line_number = line_number

    def __str__(self):
        if self.line_number is not None:
            return "Parse error at line %s: %s" % (self.line_number,
                                                   self.message)
        else:
            return self.message
