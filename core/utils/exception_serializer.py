import traceback

def serialize_exception(e: Exception) -> dict:
    return {
        "exception_type": e.__class__.__name__,
        "message": str(e),
        "traceback": traceback.format_exc(),
    }