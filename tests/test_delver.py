import json
import tempfile
import unittest

from datadelve.datadelve import ChainedDelver, DataDelver, JsonDelver, ReadonlyError


def linked_equal(a: ChainedDelver, b: ChainedDelver):
    return a.searchpath == b.searchpath


ChainedDelver.__eq__ = linked_equal


class TestDataDelver(unittest.TestCase):
    def setUp(self) -> None:
        # Sample data to be used in each method
        self.data = {
            "string": "value",
            "dict": {
                "a": "A",
                "b": "B"
            },
            "list": [
                "string",
                1,
                None,
                True
            ],
            "nesting": {
                "multiple": {
                    "levels": "here"
                }
            }
        }

    def test_get(self):
        delve = DataDelver(self.data)
        self.assertEqual(delve.get('/string'), 'value')
        self.assertEqual(delve.get('/dict/a'), 'A')
        self.assertEqual(delve.get('/list/3'), True)
        self.assertEqual(delve.get('/'), self.data)
        self.assertIs(delve.get('/nonexistent'), None)

    def test_set(self):
        delve = DataDelver(self.data)
        delve.set('/dict/a', 'New A')
        self.assertEqual(self.data['dict']['a'], 'New A')
        delve.set('/dict', 'a dict no longer')
        self.assertEqual(self.data['dict'], 'a dict no longer')
        delve.set('/new', "new value")
        self.assertEqual(self.data['new'], 'new value')
        delve.set('/', "nothing remains")
        self.assertEqual(delve.get('/'), "nothing remains")

    def test_delete(self):
        delve = DataDelver(self.data)
        delve.delete('/dict/a')
        self.assertEqual(self.data['dict'], {'b': 'B'})
        delve.delete('/list/1')
        self.assertEqual(self.data['list'], ['string', None, True])
        delve.delete('/')
        self.assertEqual(delve.get('/'), {})

    def test_cd(self):
        delve = DataDelver(self.data)
        sub = delve.cd('/dict')
        self.assertEqual(sub.get('/a'), 'A')
        self.assertEqual(sub.get('/'), {'a': 'A', 'b': 'B'})
        sub.set('/c', 'C')
        self.assertEqual(sub.get('/c'), 'C')
        sub.delete('/a')
        self.assertEqual(sub.get('/'), {'b': 'B', 'c': 'C'})
        first = delve.cd('/nesting')
        second = first.cd('/multiple')
        self.assertEqual(second.get('/'), {'levels': 'here'})

    def test_readonly(self):
        delve = DataDelver(self.data, True)
        with self.assertRaises(ReadonlyError):
            delve.delete('/string')
        with self.assertRaises(ReadonlyError):
            delve.set('/new', 'foo')


class TestJsonDelver(unittest.TestCase):
    def setUp(self) -> None:
        self.data = {
            "string": "value",
            "dict": {
                "a": "A",
                "b": "B"
            },
            "list": [
                "string",
                1,
                None,
                True
            ]
        }
        self.file = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8')
        json.dump(self.data, self.file)
        self.file.flush()

    def test_init(self):
        delve = JsonDelver(self.file.name)
        self.assertEqual(delve.get('/'), self.data)

    def test_write(self):
        delve = JsonDelver(self.file.name)
        delve.set('/newkey', 'something')
        delve.write()
        new = JsonDelver(self.file.name)
        self.assertEqual(new.get('/newkey'), 'something')

    def test_flyweight(self):
        first = JsonDelver(self.file.name)
        second = JsonDelver(self.file.name)
        self.assertIs(first, second)

    def test_readonly(self):
        delve = JsonDelver(self.file.name, readonly=True)
        with self.assertRaises(ReadonlyError):
            delve.write()

    def tearDown(self) -> None:
        self.file.close()


class TestChainedDelver(unittest.TestCase):
    def setUp(self) -> None:
        self.data1 = {
            "string": "value",
            "dict": {
                "a": "A",
                "b": "B"
            },
            "list": [
                "string",
                1,
                None,
                True
            ]
        }
        self.data2 = {
            "string": "other",
            "list": [
                "some",
                "more"
            ],
            "dict": {
                'x': 'X',
                'y': 'Y'
            }
        }
        self.file1 = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8')
        json.dump(self.data1, self.file1)
        self.file1.flush()
        self.file2 = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8')
        json.dump(self.data2, self.file2)
        self.file2.flush()

    def test_create(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        alt = delve1 + delve2
        self.assertEqual(linked.searchpath, alt.searchpath)

    def test_get(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        self.assertEqual(linked.get('/string'), 'other')
        self.assertEqual(linked.get('/list/0'), 'some')

    def test_get_all(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        self.assertEqual(linked.get('*:/string'), ['value', 'other'])
        self.assertEqual(linked.get('*:/list'), ['string', 1, None, True, 'some', 'more'])
        self.assertEqual(linked.get('*:/dict'), {'a': 'A', 'b': 'B', 'x': 'X', 'y': 'Y'})

    def test_get_specific(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        self.assertEqual(linked.get(str(delve1.filename) + ':/string'), 'value')

    def test_add(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        added = delve1 + delve2
        constructed = ChainedDelver(delve1, delve2)
        self.assertEqual(added, constructed)
        iadded = ChainedDelver(delve1)
        iadded += delve2
        self.assertEqual(iadded, constructed)
        self.assertEqual(ChainedDelver(delve1, delve2, delve1, delve2),
                         added + constructed)

    def tearDown(self) -> None:
        self.file1.close()
        self.file2.close()


if __name__ == '__main__':
    unittest.main()
