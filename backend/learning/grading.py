"""Conservative lexical grading. Never execute submitted Python or SQL."""
import re
SQL_KEYWORDS = frozenset("ROW_NUMBER RANK DENSE_RANK LAG LEAD SELECT FROM WHERE AND OR NOT NULL IS AS DISTINCT ORDER BY ASC DESC GROUP HAVING JOIN INNER LEFT RIGHT FULL OUTER CROSS ON UNION ALL INTERSECT EXCEPT WITH RECURSIVE OVER PARTITION ROWS RANGE BETWEEN UNBOUNDED PRECEDING FOLLOWING CURRENT ROW CASE WHEN THEN ELSE END IN EXISTS LIKE ESCAPE LIMIT OFFSET FETCH FIRST ONLY INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE INDEX DROP ALTER ADD PRIMARY KEY FOREIGN REFERENCES UNIQUE CHECK DEFAULT COUNT SUM AVG MIN MAX COALESCE CAST INTEGER VARCHAR TEXT DATE TRUE FALSE BEGIN COMMIT ROLLBACK SAVEPOINT RELEASE NULLIF USING NATURAL WINDOW FILTER EXTRACT COLLATE".split())
TOKEN = re.compile(r'''(?:'(?:''|[^'])*'|"(?:""|[^"])*"|[A-Za-z_][A-Za-z_0-9$]*|\d+(?:\.\d+)?|<=|>=|<>|!=|\|\||[^\s])''')
def normalize_python(value):
    return value.strip()
def normalize_sql(value):
    tokens = TOKEN.findall(value.strip())
    if any(token in ("'", '"', '`', '[', ']') for token in tokens) or any(tokens[i:i+2] in (['-','-'], ['/','*']) for i in range(len(tokens)-1)):
        return ('unparsed', value)
    # Unknown identifiers and quoted literals retain spelling and case.
    return tuple(token.upper() if token.upper() in SQL_KEYWORDS and re.fullmatch(r'[A-Za-z_]+', token) else token for token in tokens)
def answers_match(subject, question_type, submitted, correct):
    if subject == 'sql' and question_type == 'fill_blank':
        return normalize_sql(submitted) == normalize_sql(correct)
    return normalize_python(submitted) == normalize_python(correct)
