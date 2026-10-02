"""Bound streaming request bodies even when Content-Length is absent."""
from fastapi import HTTPException
from threading import Lock
import shutil


class TemporaryBudget:
    """Reserve multipart spool capacity before parsing, even without a length.

    Compose disk volumes have no portable size quota. This limits this app's
    concurrent spools to 1 GiB; Kubernetes additionally enforces emptyDir size.
    """
    def __init__(self, capacity=1024*1024*1024):
        self.capacity=capacity
        self.reserved=0
        self.lock=Lock()

    def reserve(self, amount, path, minimum_free):
        with self.lock:
            if amount+self.reserved>self.capacity:
                raise HTTPException(503,'TEMPORARY_STORAGE_BUSY')
            if shutil.disk_usage(path).free<amount+self.reserved+minimum_free:
                raise HTTPException(503,'TEMPORARY_STORAGE_LOW')
            self.reserved+=amount

    def release(self, amount):
        with self.lock:
            self.reserved-=amount


class RequestBodyLimit:
    def __init__(self,app,max_bytes):
        self.app,self.max_bytes=app,max_bytes

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or not scope.get('path','').startswith('/api/'):
            return await self.app(scope,receive,send)
        consumed=0
        async def bounded_receive():
            nonlocal consumed
            message=await receive()
            if message['type']=='http.request':
                consumed+=len(message.get('body',b''))
                if consumed>self.max_bytes:
                    raise HTTPException(413,'UPLOAD_TOO_LARGE')
            return message
        await self.app(scope,bounded_receive,send)
