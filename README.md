# plugin_haystack.py

This is an experimental plugin to provide full text-search for web2py.

## How to use it?

Assume the following model:

    db = DAL()
    db.define_table('thing', Field('name'), Field('description'))

You want to be able to perform full text search on the two fields of the above table. You do:

    from plugin_haystack import Haystack
    index = Haystack(db.thing)
    index.indexes('name', 'description')

This will create indexes for all new records inserted, modified, and deleted from the above table. For example:

     db.thing.insert(name='Char', description='A char') # automatically indexed
     db(db.thing.id).update(description='The chair')   # automatically re-indexed
     db(db.thing).delete()                             # automatically re-indexed                                                                                            
You can now use Haystack to build queries:

     query = index.search(name='chair', description='chair')

and use in combinations with other DAL queries:
                                                                                                                    
     print db(query)(db.thing.name.endswith('r')).select() 

## Supported backends:

*Simple* (mostly for testing):

    index = Haystack(db.thing)

*Whoosh* (you must `pip install whoosh`):

    index = Haystack(db.thing, backend=WhooshBackend, indexdir='/path/to/index')

*Solr* (you must install and run Solr, and `pip install sunburnt`)

    index = Haystack(db.thing, backend=SolrBackend, url='https://localhost:8983')

## How does it works?

web2py Haystack uses a third party backend - built on the local database or on file (Whoosh) or as a web service (Solr) - to create an index of keywords to records in the table (db.thing in the example). When you call:

    index.search(name='chair')

It performs a query to the backend to get a list of records ids which match the query. It returns the query:

    db.thing.belongs([3, 5, 9, ...])

Therefore:

    rows = db(index.search(name='chair')).select()

is the same as 

    // find the ids of all records with name matching "chair" and
    rows = db(db.thing.id.belongs(ids)).select()

## Caveats

- How the record matching is done depends on the backend. In the Simple case it converts the text to lower case  and break the text into tokens (worlds longer then 3 alphanumeric chars), then looks for all indexed records which contain all tokens in the queries text. It returns the first 20 entries found. In the Whoosh case and the Solr case it returns the closest matches, defined by others and more complex algorithms.

- Web2py does automatic migrations. Haystack does not. This means you cannot simply change the list of indexed fields and expect the index to work. Eventually there should be a way to rebuild the indexes but this has not been implemented yet.
