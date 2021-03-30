import json
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

from datadelve import ChainedDelver, DataDelver, JsonDelver, ReadonlyError, MergeError, \
    IterationError, PathError, InvalidFileError, UnreadableFileError, DuplicateInChainError, \
    MergeStrategy


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
        self.assertEqual(delve.get(''), self.data)
        self.assertIs(delve.get('/nonexistent'), None)

    def test_set(self):
        delve = DataDelver(self.data)
        delve.set('/dict/a', 'New A')
        self.assertEqual(self.data['dict']['a'], 'New A')
        delve.set('/dict', 'a dict no longer')
        self.assertEqual(self.data['dict'], 'a dict no longer')
        delve.set('/new', "new value")
        self.assertEqual(self.data['new'], 'new value')
        delve.set('', "nothing remains")
        self.assertEqual(delve.get(''), "nothing remains")

    def test_delete(self):
        delve = DataDelver(self.data)
        delve.delete('/dict/a')
        self.assertEqual(self.data['dict'], {'b': 'B'})
        delve.delete('/list/1')
        self.assertEqual(self.data['list'], ['string', None, True])
        with self.assertRaises(PathError):
            delve.delete('/nonexistent')
        with self.assertRaises(PathError):
            delve.delete('/dict/nonexistent')
        with self.assertRaises(PathError):
            delve.delete('/dict/nested/nonexistent')
        delve.delete('')
        self.assertEqual(delve.get(''), {})

    def test_cd(self):
        delve = DataDelver(self.data)
        sub = delve.cd('/dict')
        self.assertEqual(sub.get('/a'), 'A')
        self.assertEqual(sub.get(''), {'a': 'A', 'b': 'B'})
        sub.set('/c', 'C')
        self.assertEqual(sub.get('/c'), 'C')
        sub.delete('/a')
        self.assertEqual(sub.get(''), {'b': 'B', 'c': 'C'})
        first = delve.cd('/nesting')
        second = first.cd('/multiple')
        self.assertEqual(second.get(''), {'levels': 'here'})

    def test_readonly(self):
        delve = DataDelver(self.data, True)
        with self.assertRaises(ReadonlyError):
            delve.delete('/string')
        with self.assertRaises(ReadonlyError):
            delve.set('/new', 'foo')

    def test_iter(self):
        delve = DataDelver(self.data)
        for get_pair, orig_pair in zip(delve, self.data.items()):
            self.assertEqual(get_pair, orig_pair)
        child = delve.cd('/list')
        for pulled, original in zip(child, self.data['list']):
            self.assertEqual(pulled, original)
        scalar = delve.cd('/string')
        with self.assertRaises(IterationError):
            for impossible in scalar:
                pass

    def test_set_root_after_cd(self):
        delve = DataDelver(self.data)
        sub = delve.cd('/dict')
        delve.set('', {'dict': 'replaced'})
        self.assertEqual(sub.get(''), 'replaced')

    def test_readonly_cd(self):
        delve = DataDelver(self.data)
        sub = delve.cd('/dict', readonly=True)
        with self.assertRaises(ReadonlyError):
            sub.set('/new', 12)
        with self.assertRaises(ReadonlyError):
            sub.delete('/c')

    def test_set_without_intermediate(self):
        delve = DataDelver(self.data)
        with self.assertRaises(PathError):
            delve.set('/nonexistent/path', 'foo')


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
        self.file = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8', delete=False)
        json.dump(self.data, self.file)
        self.file.flush()
        self.file.close()

    def test_init(self):
        delve = JsonDelver(self.file.name)
        self.assertEqual(delve.get(''), self.data)

    def test_write(self):
        delve = JsonDelver(self.file.name)
        delve.set('/newkey', 'something')
        delve.write()
        written = json.load(open(self.file.name, 'r'))
        self.assertEqual(written, delve.data)

    def test_flyweight(self):
        first = JsonDelver(self.file.name)
        second = JsonDelver(self.file.name)
        self.assertIs(first, second)

    def test_readonly(self):
        delve = JsonDelver(self.file.name, readonly=True)
        with self.assertRaises(ReadonlyError):
            delve.write()

    def test_str(self):
        delve = JsonDelver(self.file.name)
        self.assertEqual(str(delve), Path(self.file.name).name)

    def test_nonexistent_file(self):
        with self.assertRaises(UnreadableFileError):
            JsonDelver('./nonexistent')

    def test_nonjson_file(self):
        otherfile = tempfile.NamedTemporaryFile('w+')
        otherfile.write('this is not valid json')
        with self.assertRaises(InvalidFileError):
            JsonDelver(otherfile.name)

    def test_symlink(self):
        alternate = Path('/tmp/symlink')
        try:
            alternate.symlink_to(self.file.name)
            hard = JsonDelver(self.file.name)
            soft = JsonDelver(alternate)
            self.assertIs(hard, soft)
        finally:
            alternate.unlink()

    def tearDown(self) -> None:
        self.file.close()
        Path(self.file.name).unlink()


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
            },
            "sometimes": ["here"]
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
        self.assertEqual(linked.searchpath, OrderedDict([
            (str(delve1.filename), delve1), (str(delve2.filename), delve2)
        ]))

    def test_get_first(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        self.assertEqual(linked.get('/string', strategy=MergeStrategy.FIRST), 'other')
        self.assertEqual(linked.get('/list/0', strategy=MergeStrategy.FIRST), 'some')
        self.assertEqual(linked.get('/nonexistent'), None)

    def test_get_merge(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        self.assertEqual(linked.get('/list', strategy=MergeStrategy.MERGE),
                         ['string', 1, None, True, 'some', 'more'])
        self.assertEqual(linked.get('/dict', strategy=MergeStrategy.MERGE),
                         {'a': 'A', 'b': 'B', 'x': 'X', 'y': 'Y'})
        self.assertEqual(linked.get('/sometimes', strategy=MergeStrategy.MERGE), ['here'])
        with self.assertRaises(MergeError):
            linked.get('/string', strategy=MergeStrategy.MERGE)

    def test_get_collect(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        self.assertEqual(linked.get('/string', strategy=MergeStrategy.COLLECT),
                         ['other', 'value'])
        self.assertEqual(linked.get('/list', strategy=MergeStrategy.COLLECT),
                         [['some', 'more'], ['string', 1, None, True]])
        self.assertEqual(linked.get('/dict', strategy=MergeStrategy.COLLECT),
                         [{'x': 'X', 'y': 'Y'}, {'a': 'A', 'b': 'B'}])
        self.assertEqual(linked.get('/sometimes', strategy=MergeStrategy.COLLECT), [['here']])

    def test_retrieve(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        self.assertIs(linked[self.file1.name], delve1)

    def test_symlink(self):
        link = Path('/tmp/symlink')
        try:
            link.symlink_to(self.file1.name)
            delve1 = JsonDelver(self.file1.name)
            delve2 = JsonDelver(link)
            with self.assertRaises(DuplicateInChainError):
                ChainedDelver(delve1, delve2)
        finally:
            link.unlink()

    def test_set(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        linked.set('/new', 'foo')
        self.assertEqual(linked.get('/new'), 'foo')

    def test_delete(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        linked.delete('/list')
        self.assertIsNone(linked.get('/list'))

    def test_delete_readonly(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name, readonly=True)
        linked = ChainedDelver(delve1, delve2)
        with self.assertRaises(ReadonlyError):
            linked.delete('/list')

    def test_delete_nonexistent(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        linked.delete('/nonexistent')

    def test_cd(self):
        delve1 = JsonDelver(self.file1.name)
        delve2 = JsonDelver(self.file2.name)
        linked = ChainedDelver(delve1, delve2)
        subset = linked.cd('/dict')
        self.assertEqual(subset.get('/a'), 'A')
        self.assertEqual(subset.get('/x'), 'X')

    def tearDown(self) -> None:
        self.file1.close()
        self.file2.close()


if __name__ == '__main__':
    unittest.main()
