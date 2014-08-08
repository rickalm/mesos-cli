# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from __future__ import absolute_import, print_function

import itertools
import os

from . import exceptions, util


class File(object):

    chunk_size = 1024

    def __init__(self, host, task=None, path=None):
        self.host = host
        self.task = task
        self.path = path

        if self.task is None:
            self._host_path = self.path
        else:
            self._host_path = os.path.join(self.task.directory, self.path)

        self._offset = 0

        # Used during fetch, class level so the dict isn't constantly alloc'd
        self._params = {
            "path": self._host_path,
            "offset": -1,
            "length": self.chunk_size
        }

    def __iter__(self):
        for line in self._readlines():
            yield line

    def __eq__(self, y):
        return self.key() == y.key()

    def __hash__(self):
        return hash(self.key())

    def __repr__(self):
        return "<open file '{0}', for '{1}'>".format(self.path, self._where)

    def __str__(self):
        return "{0}:{1}".format(self._where, self.path)

    def key(self):
        return "{0}:{1}".format(self.host.key(), self._host_path)

    @property
    def _where(self):
        return self.task["id"] if self.task is not None else self.host.key()

    def __reversed__(self):
        for i, line in enumerate(self._readlines_reverse()):
            # Don't include the terminator when reading in reverse.
            if i == 0 and line == "":
                continue
            yield line

    def _fetch(self):
        resp = self.host.fetch("/files/read.json", params=self._params)
        if resp.status_code == 404:
            raise exceptions.FileDNE("No such file or directory.")
        return resp.json()

    def exists(self):
        try:
            self._fetch()
            return True
        except exceptions.FileDNE:
            return False

    @property
    def size(self):
        return self._fetch()["offset"]

    def seek(self, offset, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            self._offset = 0 + offset
        elif whence == os.SEEK_CUR:
            self._offset += offset
        elif whence == os.SEEK_END:
            self._offset = self.size + offset

    def tell(self):
        return self._offset

    def _length(self, start, size):
        if size and self.tell() - start + self.chunk_size > size:
            return size - (self.tell() - start)
        return self.chunk_size

    def _get_chunk(self, loc, size=None):
        if size is None:
            size = self.chunk_size

        self.seek(loc, os.SEEK_SET)
        self._params["offset"] = loc
        self._params["length"] = size

        data = self._fetch()["data"]
        self.seek(len(data), os.SEEK_CUR)
        return data

    def _read(self, size=None):
        start = self.tell()

        fn = lambda: self._get_chunk(
            self.tell(),
            size=self._length(start, size))
        pre = lambda x: x == ""
        post = lambda x: size and (self.tell() - start) >= size

        for blob in util.iter_until(fn, pre, post):
            yield blob

    def _read_reverse(self, size=None):
        fsize = self.size
        if not size:
            size = fsize

        blocks = itertools.imap(
            lambda x: x,
            xrange(fsize - self.chunk_size, fsize - size, -self.chunk_size))

        try:
            while 1:
                yield self._get_chunk(blocks.next())
        except StopIteration:
            pass

        yield self._get_chunk(fsize - size, size % self.chunk_size)

    def read(self, size=None):
        return ''.join(self._read(size))

    def readline(self, size=None):
        for line in self._readlines(size):
            return line

    def _readlines(self, size=None):
        last = ""
        for blob in self._read(size):

            # This is not streaming and assumes small chunk sizes
            blob_lines = (last + blob).split("\n")
            for line in itertools.islice(blob_lines, 0, len(blob_lines) - 1):
                yield line

            last = blob_lines[-1]

    def _readlines_reverse(self, size=None):
        buf = ""
        for blob in self._read_reverse(size):

            blob_lines = (blob + buf).split("\n")
            for line in itertools.islice(
                    reversed(blob_lines), 0, len(blob_lines) - 1):
                yield line

            buf = blob_lines[0]
        yield buf

    def readlines(self, size=None):
        return list(self._readlines(size))
