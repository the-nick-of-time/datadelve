import json
import tempfile
import unittest

from datadelve.datadelve import ChainedDelver, DataDelver, JsonDelver


def linked_equal(a: ChainedDelver, b: ChainedDelver):
    return a.searchpath == b.searchpath


ChainedDelver.__eq__ = linked_equal


class TestDataInterface(unittest.TestCase):
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
        inter = DataDelver(self.data)
        self.assertEqual(inter.get('/string'), 'value')
        self.assertEqual(inter.get('/dict/a'), 'A')
        self.assertEqual(inter.get('/list/3'), True)
        self.assertEqual(inter.get('/'), self.data)
        self.assertIs(inter.get('/nonexistent'), None)

    def test_set(self):
        inter = DataDelver(self.data)
        inter.set('/dict/a', 'New A')
        self.assertEqual(self.data['dict']['a'], 'New A')
        inter.set('/dict', 'a dict no longer')
        self.assertEqual(self.data['dict'], 'a dict no longer')
        inter.set('/new', "new value")
        self.assertEqual(self.data['new'], 'new value')
        inter.set('/', "nothing remains")
        self.assertEqual(inter.get('/'), "nothing remains")

    def test_delete(self):
        inter = DataDelver(self.data)
        inter.delete('/dict/a')
        self.assertEqual(self.data['dict'], {'b': 'B'})
        inter.delete('/list/1')
        self.assertEqual(self.data['list'], ['string', None, True])
        inter.delete('/')
        self.assertEqual(inter.get('/'), {})

    def test_cd(self):
        inter = DataDelver(self.data)
        sub = inter.cd('/dict')
        self.assertEqual(sub.get('/a'), 'A')
        self.assertEqual(sub.get('/'), {'a': 'A', 'b': 'B'})
        sub.set('/c', 'C')
        self.assertEqual(sub.get('/c'), 'C')
        sub.delete('/a')
        self.assertEqual(sub.get('/'), {'b': 'B', 'c': 'C'})
        first = inter.cd('/nesting')
        second = first.cd('/multiple')
        self.assertEqual(second.get('/'), {'levels': 'here'})


class TestJsonInterface(unittest.TestCase):
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
        inter = JsonDelver(self.file.name)
        self.assertEqual(inter.get('/'), self.data)

    def test_write(self):
        inter = JsonDelver(self.file.name)
        inter.set('/newkey', 'something')
        inter.write()
        new = JsonDelver(self.file.name)
        self.assertEqual(new.get('/newkey'), 'something')

    def tearDown(self) -> None:
        self.file.close()


class TestLinkedInterface(unittest.TestCase):
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
        inter1 = JsonDelver(self.file1.name)
        inter2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(inter1, inter2)
        alt = inter1 + inter2
        self.assertEqual(linked.searchpath, alt.searchpath)

    def test_get(self):
        inter1 = JsonDelver(self.file1.name)
        inter2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(inter1, inter2)
        self.assertEqual(linked.get('/string'), 'other')
        self.assertEqual(linked.get('/list/0'), 'some')

    def test_get_all(self):
        inter1 = JsonDelver(self.file1.name)
        inter2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(inter1, inter2)
        self.assertEqual(linked.get('*:/string'), ['value', 'other'])
        self.assertEqual(linked.get('*:/list'), ['string', 1, None, True, 'some', 'more'])
        self.assertEqual(linked.get('*:/dict'), {'a': 'A', 'b': 'B', 'x': 'X', 'y': 'Y'})

    def test_get_specific(self):
        inter1 = JsonDelver(self.file1.name)
        inter2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(inter1, inter2)
        self.assertEqual(linked.get(str(inter1.filename) + ':/string'), 'value')

    def test_add(self):
        inter1 = JsonDelver(self.file1.name)
        inter2 = JsonDelver(self.file2.name)
        added = inter1 + inter2
        constructed = ChainedDelver(inter1, inter2)
        self.assertEqual(added, constructed)
        iadded = ChainedDelver(inter1)
        iadded += inter2
        self.assertEqual(iadded, constructed)
        self.assertEqual(ChainedDelver(inter1, inter2, inter1, inter2),
                         added + constructed)

    def tearDown(self) -> None:
        self.file1.close()
        self.file2.close()


if __name__ == '__main__':
    unittest.main()
