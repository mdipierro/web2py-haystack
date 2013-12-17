"""
plugin_haystack.py

This file is an experimental part of the web2py.
It allows full text search using database, Whoosh, or Solr.
Author: Massimo Di Pierro
License: LGPL

Usage:
db = DAL()
db.define_table('thing',Field('name'),Field('description'))
index = Haystack(db.thing)                        # table to be indexed
index.indexes('name','description')               # fields to be indexed
db.thing.insert(name='Char',description='A char') # automatically indexed
db(db.thing.id).update(description='The chair')   # automatically re-indexed
db(db.thing).delete()                             # automatically re-indexed
query = index.search(name='chair',description='the')
print db(query).select()
"""

import re
import os
from gluon import Field

DEBUG = True

class SimpleBackend(object):
    regex = re.compile('[\w\-]{2}[\w\-]+')
    ignore = set(['and','or','in','of','for','to','from'])
    def __init__(self, table, db = None):
        self.table = table
        self.db = db or table._db
        self.idx = self.db.define_table(
            'haystack_%s' % table._tablename,
            Field('fieldname'),
            Field('keyword'),
            Field('record_id','integer'))
    def indexes(self,*fieldnames):
        self.fieldnames = fieldnames
        return self
    def after_insert(self,fields,id):
        if DEBUG: print 'after insert',fields,id
        for fieldname in self.fieldnames:
            words = set(self.regex.findall(fields[fieldname].lower())) - self.ignore
            for word in words:
                self.idx.insert(
                    fieldname = fieldname,
                    keyword = word,
                    record_id = id)
        if DEBUG: print self.db(self.idx).select()
        return True
    def after_update(self,queryset,fields):
        if DEBUG: print 'after update',queryset,fields
        db = self.db
        for id in self.get_ids(queryset):
            for fieldname in self.fieldnames:
                if fieldname in fields:
                    words = set(self.regex.findall(fields[fieldname].lower())) - self.ignore
                    existing_words = set(r.keyword for r in db(
                            (self.idx.fieldname == fieldname)&
                            (self.idx.record_id==id)
                            ).select(self.idx.keyword))
                    db((self.idx.fieldname == fieldname)&
                       (self.idx.record_id==id)&
                       (self.idx.keyword.belongs(list(existing_words - words)))
                       ).delete()
                    for new_word in (words - existing_words):
                        self.idx.insert(
                            fieldname = fieldname,
                            keyword = new_word,
                            record_id = id)
        if DEBUG: print self.db(self.idx).select()
        return True
    def get_ids(self,queryset):
        return [r.id for r in queryset.select(self.table._id)]
    def after_delete(self,queryset):
        if DEBUG: print 'after delete',queryset
        ids = self.get_ids(queryset)
        self.db(self.idx.record_id.belongs(ids)).delete()
        if DEBUG: print self.db(self.idx).select()
        return True
    def meta_search(self,limit,mode,**fieldkeys):
        db = self.db
        ids = None
        for fieldname in fieldkeys:
            if fieldname in self.fieldnames:
                words = set(self.regex.findall(fieldkeys[fieldname].lower()))
                meta_query = ((self.idx.fieldname==fieldname)&
                              (self.idx.keyword.belongs(list(words))))
                new_ids = set(r.record_id for r in db(meta_query).select(
                        limitby=(0,limit)))
                if mode == 'and':
                    ids = new_ids if ids is None else ids & new_ids
                elif mode == 'or':
                    ids = new_ids if ids is None else ids | new_ids
        return list(ids)


class WhooshBackend(SimpleBackend):
    def __init__(self, table, indexdir):
        self.table = table
        self.indexdir = indexdir
        if not os.path.exists(indexdir):
            os.mkdir(indexdir)
    def indexes(self,*fieldnames):
        try:
            from whoosh.index import create_in
            from whoosh.fields import Schema, TEXT, ID
        except ImportError:
            raise ImportError("Cannot find Whoosh")
        self.fieldnames = fieldnames
        try:
            self.ix = open_dir(self.indexdir)
        except:
            schema = Schema(id=ID(unique=True,stored=True),
                            **dict((k,TEXT) for k in fieldnames))
            self.ix = create_in(self.indexdir, schema)
    def after_insert(self,fields,id):
        if DEBUG: print 'after insert',fields,id
        writer = self.ix.writer()
        writer.add_document(id=unicode(id),
                            **dict((name,unicode(fields[name]))
                                   for name in self.fieldnames if name in fields))
        writer.commit()
        return True
    def after_update(self,queryset,fields):
        if DEBUG: print 'after update',queryset,fields
        ids = self.get_ids(queryset)
        if ids:
            writer = self.ix.writer()
            for id in ids:
                writer.update_document(id=unicode(id),
                                       **dict((name,unicode(fields[name]))
                                              for name in self.fieldnames if name in fields))
            writer.commit()
        return True
    def after_delete(self,queryset):
        if DEBUG: print 'after delete',queryset
        ids = self.get_ids(queryset)
        if ids:
            writer = self.ix.writer()
            for id in ids:
                writer.delete_by_term('id', unicode(id))
            writer.commit()
        return True
    def meta_search(self,limit,mode,**fieldkeys):
        from whoosh.qparser import QueryParser
        ids = None
        with self.ix.searcher() as searcher:
            for fieldname in fieldkeys:
                parser = QueryParser(fieldname, schema=self.ix.schema)
                query = parser.parse(unicode(fieldkeys[fieldname]))
                results = searcher.search(query,limit=limit)
                new_ids = set(long(result['id']) for result in results)
                if mode == 'and':
                    ids = new_ids if ids is None else ids & new_ids
                elif mode == 'or':
                    ids = new_ids if ids is None else ids | new_ids
        return list(ids)


class SolrBackend(SimpleBackend):
    def __init__(self, table, url="http://localhost:8983",schema_filename="schema.xml"):
        self.table = table
        self.url = url
        self.schema_filename=schema_filename
    def indexes(self,*fieldnames):
        try:
            import sunburnt
        except ImportError:
            raise ImportError("Cannot find sunburnt, it is necessary to access Solr")
        self.fieldnames = fieldnames
        if not os.path.exists(self.schema_filename):
            schema='<fields><field name="id" type="int" indexed="true" stored="true" required="true" />%s</fields>' \
                % ''.join('<field name="%s" type="string" />' % name for name in fieldname)
            open(self.schema_filename,'w').write(shema)
        try:
            self.interface = sunburnt.SolrInterface(self.url, self.schema_filename)
        except:
            raise RuntimeError("Cannot connect to Solr: %s" % self.url)
    def after_insert(self,fields,id):
        if DEBUG: print 'after insert',fields,id
        document = {'id':id}
        for name in self.fieldnames:
            if name in fields:
                document[name] = unicode(fields[name])
        self.interface.add([document])
        self.interface.commit()
        return True
    def after_update(self,queryset,fields):
        """ caveat, this should work but only if ALL indexed fields are updated at once """
        if DEBUG: print 'after update',queryset,fields
        ids = self.get_ids(queryset)
        self.interface.delete(ids)
        documents = []
        for id in ids:
            document = {'id':id}
            for name in self.fieldnames:
                if name in fields:
                    document[name] = unicode(fields[name])
            documents.append(document)
        self.interface.add(documents)
        self.interface.commit()
        return True
    def after_delete(self,queryset):
        if DEBUG: print 'after delete',queryset
        ids = self.get_ids(queryset)
        self.interface.delete(ids)
        self.interface.commit()
        return True
    def meta_search(self,limit,mode,**fieldkeys):
        """ mode is ignored hhere since I am not sure what Solr does  """
        results = self.interface.query(**fieldkeys).paginate(0,limit)
        ids = [r['id'] for r in results]
        return ids


class Haystack(object):
    def __init__(self,table,backend=SimpleBackend,**attr):
        self.table = table
        self.backend = backend(table,**attr)
    def indexes(self,*fieldnames):
        invalid = [f for f in fieldnames if not f in self.table.fields() or
                   not self.table[f].type in ('string','text')]
        if invalid:
            raise RuntimeError("Unable to index fields: %s" % ', '.join(invalid))
        self.backend.indexes(*fieldnames)
        self.table._after_insert.append(
            lambda fields,id: self.backend.after_insert(fields,id))
        self.table._after_update.append(
            lambda queryset,fields: self.backend.after_update(queryset,fields))
        self.table._after_delete.append(
            lambda queryset: self.backend.after_delete(queryset))
    def search(self,limit=20,mode='and',**fieldkeys):
        ids = self.backend.meta_search(limit,mode,**fieldkeys)
        return self.table._id.belongs(ids)

def test(mode='simple'):
    db = DAL()
    db.define_table('thing',Field('name'),Field('description','text'))
    if mode=='simple':
        index = Haystack(db.thing)
    elif mode=='whoosh':
        index = Haystack(db.thing,backend=WhooshBackend,indexdir='test-whoosh')
    elif mode=='solr':
        index = Haystack(db.thing,backend=SolrBackend,url='https://localhost:8983')
    index.indexes('name','description')
    id = db.thing.insert(name="table",description = "one table")
    id = db.thing.insert(name="table",description = "another table")
    assert db(index.search(description='one')).count()==1
    assert db(index.search(description='table')).count()==2
    assert db(index.search(name='table')).count()==2
    assert db(index.search(name='table',description='table')).count()==2
    db(db.thing.id==id).update(name='table',description='four legs')
    assert db(index.search(description='another')).count()==0
    assert db(index.search(description='four')).count()==1
    assert db(index.search(description='legs')).count()==1
    assert db(index.search(description='legs four')).count()==1
    assert db(index.search(name='table')).count()==2
    assert db(index.search(name='table',description='table')).count()==1
    assert db(index.search(name='table')|
              index.search(description='table')).count()==2
    db(db.thing.id==id).delete()
    assert db(index.search(name='table')).count()==1
    db(db.thing).delete()
    assert db(index.search(name='table')).count()==0
    db.commit()
    db.close()

if __name__=='__main__':
    test('simple')
    test('whoosh')
