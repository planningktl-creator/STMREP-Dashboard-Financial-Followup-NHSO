"""Bound streaming request bodies even when Content-Length is absent."""
from starlette.exceptions import HTTPException


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
