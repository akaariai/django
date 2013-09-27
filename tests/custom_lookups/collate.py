import re

from django.db.models.datastructures import RefCol

class Collate(RefCol):
    def __init__(self, col_name, lang):
        super(Collate, self).__init__(col_name)
        if not re.match(r'([\w\-_])*', lang):
            raise ValueError('Given language code "%s" not in correct format' %
                             lang)
        self.lang = lang

    def as_sql(self, qn, connection):
        sql, params = self.col.as_sql(qn, connection)
        # Unfortunately collate language can't be passed in as param -
        # injection risk here...
        return '((%s) COLLATE "%s")' % (sql, self.lang), params
