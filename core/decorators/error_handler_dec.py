from fastapi import HTTPException
from icecream import ic
import inspect,asyncio
from functools import wraps
from hyperlocal_platform.core.models.req_res_models import BaseResponseTypDict,ErrorResponseTypDict,SuccessResponseTypDict
from sqlalchemy.exc import IntegrityError
from asyncpg.exceptions import ForeignKeyViolationError

def catch_errors(func):
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise

            except IntegrityError as e:
                print("Origi",e.orig,"Detail",e.detail,"code",e.code)
                if e.code=="gkpj":
                    raise HTTPException(
                        status_code=400,
                        detail=ErrorResponseTypDict(
                            status_code=400,
                            description="Invalid ids",
                            msg="Error : Some of the ID are not matching, please ensure all are correct",
                            success=False
                        )
                    )
                
            except Exception as e:
                ic(f"Error at {func.__name__} -> {e}")
                raise HTTPException(
                    status_code=500, 
                    detail=ErrorResponseTypDict(
                        status_code=500,
                        msg="Error : Internal server error",
                        description="Try agin the request after sometimes , if it's persist. contact our team support@debuggers.com",
                        succsess=False
                    )
                )
        return wrapper

    else:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                ic(f"Error at {func.__name__} -> {e}")
                raise HTTPException(
                    status_code=500, 
                    detail=ErrorResponseTypDict(
                        status_code=500,
                        msg="Error : Internal server error",
                        description="Try agin the request after sometimes , if it's persist. contact our team support@debuggers.com",
                        succsess=False
                    )
                )
            
        return wrapper