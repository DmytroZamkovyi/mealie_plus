import asyncio

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from custom_components.shopping_sync.core.models import SrcNew
from custom_components.shopping_sync.mealie import MealieAuthError, MealieClient


def make_app():
    state = {"items": [], "puts": [], "deleted": [], "merge": False}
    app = web.Application()

    async def lists(request):
        if request.headers.get("Authorization") != "Bearer tok":
            return web.Response(status=401)
        return web.json_response({"page": 1, "total_pages": 1, "items": [{"id": "L1", "name": "Метро", "x": 1}]})

    async def units(request):
        return web.json_response({"page": 1, "total_pages": 1, "items": [{"id": "U1", "name": "штука"}]})

    async def items_get(request):
        page = int(request.query.get("page", 1))
        # two pages to check paging
        chunk = state["items"][(page - 1) * 1 : page * 1]
        return web.json_response({"page": page, "total_pages": max(1, len(state["items"])), "items": chunk})

    async def items_post(request):
        body = await request.json()
        state["last_post"] = body
        if state["merge"]:
            return web.json_response({"createdItems": [], "updatedItems": [{"id": "EXIST"}], "deletedItems": []})
        return web.json_response({"createdItems": [{"id": "NEW1"}], "updatedItems": [], "deletedItems": []})

    async def items_put(request):
        state["puts"].append(await request.json())
        return web.json_response({})

    async def items_delete(request):
        state["deleted"] += request.query.getall("ids")
        return web.json_response({})

    app.router.add_get("/api/households/shopping/lists", lists)
    app.router.add_get("/api/units", units)
    app.router.add_get("/api/households/shopping/items", items_get)
    app.router.add_post("/api/households/shopping/items", items_post)
    app.router.add_put("/api/households/shopping/items", items_put)
    app.router.add_delete("/api/households/shopping/items", items_delete)
    return app, state


def raw(i, list_id, qty, checked=False, food="кріп", unit="штука"):
    return {
        "id": i, "shoppingListId": list_id, "checked": checked, "quantity": qty, "note": "",
        "foodId": "F", "unitId": "U1", "food": {"name": food}, "unit": {"name": unit}, "labelId": None,
        "position": 0, "extras": {},
    }


def test_client_round_trip():
    async def go():
        app, state = make_app()
        async with TestServer(app) as srv, ClientSession() as session:
            url = f"http://{srv.host}:{srv.port}/"
            c = MealieClient(session, url, "tok")
            assert await c.lists() == [{"id": "L1", "name": "Метро"}]
            await c.units()
            state["items"] = [raw("a", "L1", 2.0), raw("b", "L2", 0, True)]
            got = await c.items()  # paging: two pages
            assert [i.id for i in got["L1"]] == ["a"] and got["L1"][0].qty == 2.0
            assert got["L2"][0].qty is None and got["L2"][0].checked
            await c.set_checked(["a"], True)
            assert state["puts"][0][0]["checked"] is True and state["puts"][0][0]["foodId"] == "F"
            await c.delete(["a", "b"])
            assert state["deleted"] == ["a", "b"]
            new = SrcNew("t", "L1", "F", "кріп", "штука", 2.0, "")
            assert await c.create_item(new) == "NEW1"
            assert state["last_post"]["unitId"] == "U1" and state["last_post"]["quantity"] == 2.0
            state["merge"] = True
            assert await c.create_item(new) == "EXIST"  # merged by Mealie into an existing item
            # unknown unit without a food goes into the note
            await c.create_item(SrcNew("t", "L1", None, None, "трохи", None, "сіль"))
            assert state["last_post"]["note"] == "трохи сіль" and "foodId" not in state["last_post"]

    asyncio.run(go())


def test_bad_token():
    async def go():
        app, _ = make_app()
        async with TestServer(app) as srv, ClientSession() as session:
            c = MealieClient(session, f"http://{srv.host}:{srv.port}", "wrong")
            try:
                await c.lists()
            except MealieAuthError:
                return True
            return False

    assert asyncio.run(go())
