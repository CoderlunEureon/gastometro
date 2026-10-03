import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

// Build-time access to the aggregates produced by the Python pipeline.
const DATA_DIR = join(process.cwd(), 'public', 'data');

export function readJson<T = any>(name: string): T {
  return JSON.parse(readFileSync(join(DATA_DIR, name), 'utf-8')) as T;
}

export function deputyIds(): number[] {
  const dir = join(DATA_DIR, 'deputados');
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.endsWith('.json')).map((f) => Number(f.replace('.json', '')));
}

export interface Meta {
  gerado_em: string;
  legislatura: number;
  anos: number[];
  periodo: { inicio: string; fim: string };
  totais: { despesas: number; valor: number; deputados: number; fornecedores: number };
  liderancas: { despesas: number; valor: number };
  arquivos: Array<{ arquivo: string; ano: number; url: string | null; atualizado_na_fonte: string | null; baixado_em: string | null; linhas_lidas: number; linhas_carregadas: number; linhas_rejeitadas: number; linhas_outra_legislatura: number }>;
  fonte: { nome: string; url: string; arquivos: string; api: string };
  cota_por_uf: Record<string, number>;
}

export const meta = (): Meta => readJson<Meta>('meta.json');
