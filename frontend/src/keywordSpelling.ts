export const keywordSpelling = (name: string) => name.trim().split(/\s+/).map(w => w[0].toUpperCase() + w.slice(1)).join('')
