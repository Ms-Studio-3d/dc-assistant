"""Parse the naming convention explicitly configured for one project."""

import re

from .constants import ROLE_LABELS


class NamingRule:
    def __init__(self, settings):
        self.settings = settings
        self.parts = settings.get("parts", [])
        self.separator = settings.get("separator", "-")
        self.ignore_case = settings.get("ignore_case", False)
        if not self.parts or not self.separator:
            raise ValueError("حدد مثال التسمية وأجزاءه أولًا")
        roles = [part["role"] for part in self.parts if part["role"] != "literal"]
        if "number" not in roles:
            raise ValueError("حدد الجزء الذي يمثل رقم اللوحة التسلسلي في المثال")
        if len(roles) != len(set(roles)):
            raise ValueError(
                "كل جزء متغير يستخدم مرة واحدة؛ استخدم جزءًا ثابتًا للتكرار"
            )
        if "revision" in roles and self.parts[-1]["role"] != "revision":
            raise ValueError(
                "هذه النسخة تدعم الإصدار في آخر الاسم أو في عمود منفصل باللوج"
            )
        self.optional_revision = bool(settings.get("optional_revision", True))
        self.project_index = next(
            (i for i, part in enumerate(self.parts) if part["role"] == "project"), None
        )
        separator = re.escape(self.separator)
        pieces = []
        for index, part in enumerate(self.parts):
            role = part["role"]
            sample = str(part["sample"])
            if role not in ROLE_LABELS or not sample:
                raise ValueError("راجع تعريف أجزاء اسم اللوحة")
            if role == "literal":
                token = re.escape(sample)
            elif role == "project":
                codes = [sample, *settings.get("project_aliases", [])]
                if any(not isinstance(code, str) or not code for code in codes):
                    raise ValueError("بدائل كود المشروع يجب أن تكون نصوصًا غير فارغة")
                for left in codes:
                    for right in codes:
                        if left != right and self.key(right).startswith(
                            self.key(left + self.separator)
                        ):
                            raise ValueError(
                                "بدائل كود المشروع متداخلة مع فاصل الأجزاء؛ يلزم تعريف غير ملتبس"
                            )
                token = (
                    "(?:"
                    + "|".join(
                        re.escape(code)
                        for code in sorted(set(codes), key=len, reverse=True)
                    )
                    + ")"
                )
            else:
                # Unicode letters/digits, '_' and '+' are permitted within a part.
                # A configured separator still separates parts, regardless of alphabet.
                token = rf"(?:(?!{separator})[\w+])+"
            chunk = (separator if index else "") + f"(?P<part_{index}>{token})"
            if role == "revision" and self.optional_revision:
                chunk = f"(?:{chunk})?"
            pieces.append(chunk)
        flags = re.IGNORECASE if self.ignore_case else 0
        self.pattern = re.compile("".join(pieces), flags)

    def key(self, value):
        return value.casefold() if self.ignore_case else value

    def revision(self, value):
        if value is None or value == "":
            return ""
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        value = str(value).strip()
        sample = next(
            (str(part["sample"]) for part in self.parts if part["role"] == "revision"),
            "",
        )
        if sample.isdigit() and re.fullmatch(r"\d+\.0", value):
            value = value[:-2]
        if sample.isdigit() and value.isdigit():
            return value.zfill(len(sample))
        return value

    def _normalize(self, value):
        # A dot followed by whitespace can be sentence punctuation, not an ID.
        if self.separator == ".":
            return value
        return re.sub(
            r"\s*" + re.escape(self.separator) + r"\s*",
            lambda _: self.separator,
            value,
        )

    def parse(self, value):
        value = re.sub(r"\.(pdf|dwg)$", "", str(value).strip(), flags=re.IGNORECASE)
        match = self.pattern.fullmatch(self._normalize(value))
        if not match:
            return None
        values = [match.group(f"part_{i}") or "" for i in range(len(self.parts))]
        by_role = {part["role"]: values[i] for i, part in enumerate(self.parts)}
        document_parts = [
            values[i] for i, part in enumerate(self.parts) if part["role"] != "revision"
        ]
        canonical = document_parts[:]
        if self.project_index is not None:
            canonical[self.project_index] = str(
                self.parts[self.project_index]["sample"]
            )
        return {
            "number": self.separator.join(document_parts),
            "key": self.key(self.separator.join(canonical)),
            "revision": self.revision(by_role.get("revision", "")),
            "discipline": by_role.get("discipline", ""),
            "area": by_role.get("area", ""),
            "part_values": values,
        }

    def find_in_pdf_text(self, text):
        compact = self._normalize(text)
        found = {}
        for match in self.pattern.finditer(compact):
            if match.start() and re.match(r"[\w+]", compact[match.start() - 1]):
                continue
            if match.end() < len(compact) and re.match(r"[\w+]", compact[match.end()]):
                continue
            item = self.parse(match.group())
            if item:
                found[(item["key"], item["revision"])] = item
        return list(found.values())

    def expected_in_pdf_text(self, text, parsed):
        """Find text only. This never verifies the title-block location."""
        values = parsed["part_values"]
        codes = [None]
        if self.project_index is not None:
            codes = [
                self.parts[self.project_index]["sample"],
                *self.settings.get("project_aliases", []),
            ]
        flags = re.IGNORECASE if self.ignore_case else 0
        for code in codes:
            variant = values[:]
            if self.project_index is not None:
                variant[self.project_index] = code
            expected = self.separator.join(value for value in variant if value)
            pieces = []
            for index, char in enumerate(expected):
                pieces.append(re.escape(char))
                next_char = expected[index + 1 : index + 2]
                if next_char and not (
                    self.separator == "." and "." in (char, next_char)
                ):
                    pieces.append(r"\s*")
            pattern = r"(?<![\w+])" + "".join(pieces) + r"(?![\w+])"
            if re.search(pattern, text, flags):
                return True
        return False
