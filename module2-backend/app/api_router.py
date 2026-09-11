from fastapi import APIRouter

from app.audit.router import router as audit_router
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.checkins.router import router as checkins_router
from app.modules.courses.router import router as courses_router
from app.modules.devices.router import router as devices_router
from app.modules.enrollments.router import router as enrollments_router
from app.modules.export.router import router as export_router
from app.modules.sessions.router import router as sessions_router
from app.modules.stats.router import router as stats_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(courses_router)
api_router.include_router(sessions_router)
api_router.include_router(checkins_router)
api_router.include_router(stats_router)
api_router.include_router(devices_router)
api_router.include_router(enrollments_router)
api_router.include_router(audit_router)
api_router.include_router(export_router)
api_router.include_router(admin_router)
