import asyncio
import xmlrpc.client

# Tryton XML-RPC Server URL
TRYTON_URL = "http://localhost:8000/"
DATABASE = "your_database"


async def tryton_login(username, password):
    """Async wrapper for XML-RPC Tryton login"""
    loop = asyncio.get_running_loop()
    common = xmlrpc.client.ServerProxy(f"{TRYTON_URL}common")

    return await loop.run_in_executor(
        None, lambda: common.login(DATABASE, username, password)
    )
