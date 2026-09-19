// Require a complete explicit confirmation; negations or embedded commands never submit.
export function voiceDecision(value: string): 'submit' | 'cancel' | 'unknown' {
  const text = value.normalize('NFKC').replace(/[\s.,!?。！？]/g, '');
  if (['접수해줘','접수해주세요','접수할게요','네접수해주세요'].includes(text)) return 'submit';
  if (['취소','취소해줘','취소해주세요','아니요'].includes(text)) return 'cancel';
  return 'unknown';
}
