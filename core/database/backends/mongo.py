from pymongo import MongoClient

from pymongo.son_manipulator import SONManipulator
import pymongo.errors

from core.database.errors import DoesNotExist
import datetime

class MongoStore(object):

    def __init__(self, *args, **kwargs):
        self._connection = MongoClient(host=['localhost:27017'])
        self.db = self._connection['yeti-mongo']
        self.indexes()

    def indexes(self):
        # TODO: See if we can build this with info from each class
        self.db['internals'].create_index("name", unique=True)

store = MongoStore()

class BackendDocument(object):

    collection_name = None

    def __init__(self, *args, **kwargs):
        # This is a pretty naive field loading / object construction
        # TODO think of a better way to do this. Maybe use a mongo SON manipulator?
        self._id = kwargs.pop("_id", None)
        for name in self._fields:
            setattr(self, name, kwargs.get(name))

    def save(self):
        if getattr(self, "_id"):
            self.get_collection().replace_one({"_id": self._id}, self._to_bson())
        else:
            result = self.get_collection().insert_one(self._to_bson())
            self._id = result.inserted_id

        return self

    @classmethod
    def _from_bson(klass, bson):
        obj = klass()
        for name, field in klass._fields.items():
            value = bson.get(name)
            from core.database.fields import TimeDeltaField
            if isinstance(field, TimeDeltaField):
                value = datetime.timedelta(seconds=value)
            setattr(obj, name, value)

        return obj

    def _to_bson(self):
        bson = {}
        for name in self._fields:
            value = getattr(self, name)
            if isinstance(value, (list, tuple)):
                value = [v._to_bson() for v in value]
            if isinstance(value, (dict)):
                value = {k: v._to_bson() for k, v in value.items()}
            if isinstance(value, datetime.timedelta):
                value = value.total_seconds()
            bson[name] = value
        print "Generating BSON object"
        print bson
        return bson

    def clean_update(self, **kwargs):
        for key, value in kwargs.iteritems():
            setattr(self, key, value)

        self.validate()

        update_dict = {}
        for key, value in kwargs.iteritems():
            update_dict[key] = getattr(self, key, value)

        self.update(**update_dict)
        self.reload()
        return self

    def add_to_set(self, field, value):
        return self._set_update('$addToSet', field, value)

    def remove_from_set(self, field, value):
        return self._set_update('$pull', field, value)

    def _set_update(self, method, field, value):
        result = self.__class__.get_collection().update_one(
            {'_id': self.pk}, {method: {field: value}})
        return result.modified_count == 1

    @staticmethod
    def get_from_collection(collection, id):
        #TODO Need an index of classes to know which _from_bson method to call
        return store[collection].find_one({"_id": id})

    @classmethod
    def get(klass, **kwargs):
        obj = klass.get_collection().find_one(kwargs)
        if obj:
            return klass._from_bson(obj)
        else:
            raise DoesNotExist

    @classmethod
    def count(klass):
        return klass.get_collection().count()

    @classmethod
    def all(klass):
        return (klass._from_bson(obj) for obj in klass.get_collection().find())

    @classmethod
    def get_or_create(cls, **kwargs):
        """Attempts to save a node in the database, and loads it if duplicate"""
        obj = cls(**kwargs)
        try:
            return obj.save()
        except pymongo.errors.DuplicateKeyError:
            if hasattr(obj, 'name'):
                return cls.get(name=obj.name)
            if hasattr(obj, 'value'):
                return cls.get(value=obj.value)

    @classmethod
    def get_collection(klass):
        collection_name = klass.collection_name or klass.__name__.lower()
        return store.db[collection_name]
