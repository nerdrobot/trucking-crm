from workers import WorkerEntrypoint, asgi

from followup.app import create_app
from followup.automation import run_due
from followup.security import Settings
from followup.storage import D1Database

app = create_app()


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(app, request, self.env, self.ctx)

    async def scheduled(self, controller, env=None, ctx=None):
        await run_due(D1Database(self.env.DB), Settings.from_env(self.env))
