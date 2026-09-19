export type Role = 'elder' | 'social_worker' | 'admin' | 'caregiver';
export type User = { id: string; role: Role; status: string };
export type Category = 'meal' | 'mobility' | 'housekeeping' | 'companionship' | 'medication' | 'other';
export type Urgency = 'danger' | 'need' | 'self_care' | 'uncertain';
export type Care = { id: string; category?: Category; urgency: Urgency; created_at: string; review_required?: boolean; emergency_notice?: string | null; content?: { note: string } };
export const roles: Record<Role, string> = { elder: '어르신', social_worker: '사회복지사', admin: '관리자', caregiver: '요양보호사' };
export const categories: Record<Category, string> = { meal: '식사', mobility: '이동', housekeeping: '집안일', companionship: '말벗', medication: '복약 도움', other: '기타' };
export const urgencies: Record<Urgency, string> = { danger: '긴급 확인', need: '도움 필요', self_care: '일반 확인', uncertain: '담당자 확인' };
