import React, { useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
export const colors = { bg: '#F1F6F2', card: '#FFFFFF', green: '#176347', dark: '#153629', muted: '#526B5E', line: '#D6E2D9', danger: '#A32627' };
export function Button({ title, onPress, secondary = false, disabled = false }: { title: string; onPress: () => void; secondary?: boolean; disabled?: boolean }) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={[s.button, secondary && s.secondary, disabled && { opacity: .45 }]}><Text style={[s.buttonText, secondary && { color: colors.green }]}>{title}</Text></Pressable>;
}
export function Card({ children }: { children: React.ReactNode }) { return <View style={s.card}>{children}</View>; }
export function Field({ label, value, onChange, password = false, multiline = false, maxLength = 128 }: { label: string; value: string; onChange: (x: string) => void; password?: boolean; multiline?: boolean; maxLength?: number }) {
  return <View style={{ gap: 6 }}><Text style={s.label}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={onChange} secureTextEntry={password} autoCorrect={false} autoCapitalize="none" multiline={multiline} maxLength={maxLength} style={[s.input, multiline && { minHeight: 130, textAlignVertical: 'top' }]} /></View>;
}
export function Chips<T extends string>({ options, value, select }: { options: Record<T, string>; value: T; select: (v: T) => void }) {
  return <View style={s.wrap}>{(Object.keys(options) as T[]).map(v => <Pressable key={v} accessibilityRole="button" accessibilityState={{ selected: v === value }} onPress={() => select(v)} style={[s.chip, v === value && s.chipOn]}><Text style={[s.chipText, v === value && { color: '#fff' }]}>{options[v]}</Text></Pressable>)}</View>;
}
export function useTask() {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''); const lock = useRef(false);
  async function run(fn: () => Promise<void>) {
    if (lock.current) return; lock.current = true; setBusy(true); setMessage('');
    try { await fn(); } catch (error) { setMessage(error instanceof Error ? error.message : '처리에 실패했습니다.'); }
    finally { lock.current = false; setBusy(false); }
  }
  return { busy, message, setMessage, run };
}
export function Notice({ text }: { text: string }) { return text ? <Text accessibilityLiveRegion="polite" style={s.notice}>{text}</Text> : null; }

export const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg }, page: { padding: 20, paddingTop: 60, paddingBottom: 50, gap: 16, maxWidth: 720, width: '100%', alignSelf: 'center' },
  brand: { paddingVertical: 14, gap: 6 }, logo: { fontSize: 36, fontWeight: '800', color: colors.green, letterSpacing: -1 },
  card: { backgroundColor: colors.card, borderRadius: 22, padding: 22, gap: 16, borderWidth: 1, borderColor: colors.line }, heading: { fontSize: 25, fontWeight: '700', color: colors.dark },
  kicker: { color: colors.green, fontSize: 15, fontWeight: '700' }, body: { color: colors.muted, fontSize: 17, lineHeight: 26 }, caption: { color: colors.muted, fontSize: 14, lineHeight: 22 }, label: { color: colors.dark, fontSize: 18, fontWeight: '600' },
  input: { borderWidth: 1, borderColor: colors.line, borderRadius: 12, padding: 14, color: colors.dark, backgroundColor: '#FAFCFA', fontSize: 18, minHeight: 54 },
  button: { minHeight: 54, borderRadius: 14, backgroundColor: colors.green, padding: 15, alignItems: 'center', justifyContent: 'center' }, secondary: { backgroundColor: '#E8F2EC' }, buttonText: { color: '#fff', fontSize: 18, fontWeight: '700', textAlign: 'center' },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, chip: { paddingHorizontal: 16, paddingVertical: 13, borderWidth: 1, borderColor: colors.line, borderRadius: 24, backgroundColor: '#fff', minHeight: 48 }, chipOn: { backgroundColor: colors.green, borderColor: colors.green }, chipText: { color: colors.green, fontSize: 16, fontWeight: '600' },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: 12 }, notice: { padding: 14, borderRadius: 12, backgroundColor: '#EAF3ED', color: colors.dark, fontSize: 16, lineHeight: 25 }, emergency: { fontSize: 16, lineHeight: 25, color: colors.danger, paddingVertical: 10 }, account: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }, link: { color: colors.green, fontSize: 16, textDecorationLine: 'underline' }, cover: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: colors.bg, alignItems: 'center', justifyContent: 'center', gap: 18 },
});
