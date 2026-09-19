from aiogram import Router

from . import add, common, errors, tasks


def setup_routers() -> Router:
    root = Router(name="root")
    errors.register(root)
    root.include_router(common.router)
    root.include_router(tasks.router)
    root.include_router(add.router)  # последним: ловит любой свободный текст
    return root
