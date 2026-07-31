# -*- coding: utf-8 -*-
"""HTTP Range 요청을 지원하는 간단한 정적 파일 서버.

COG(Cloud Optimized GeoTIFF)는 파일 일부만 읽는 Range 요청으로
효율적으로 로딩되므로, 기본 http.server 대신 이 서버를 사용한다.
사용법:  python range_server.py [포트]   (기본 8000)
"""
import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        m = RANGE_RE.match(rng)
        if not m or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        start = int(m.group(1)) if m.group(1) else 0
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            self.send_error(416, "Requested Range Not Satisfiable")
            return None
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._range_len = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        n = getattr(self, "_range_len", None)
        if n is None:
            return super().copyfile(source, outputfile)
        remaining = n
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)
        self._range_len = None

    def end_headers(self):
        # 로컬 개발 서버: 항상 재검증하게 해서 index.html / catalog.json 을
        # 고쳐도 브라우저 캐시 때문에 옛 화면이 보이는 일이 없도록 한다.
        self.send_header('Cache-Control', 'no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        super().end_headers()

    def log_message(self, fmt, *args):  # 조용한 로그
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = partial(RangeHandler, directory=os.path.dirname(os.path.abspath(__file__)))
    httpd = ThreadingHTTPServer(("", port), handler)
    print(f"Arctic 데이터 뷰어: http://localhost:{port}  (Ctrl+C 종료)")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
