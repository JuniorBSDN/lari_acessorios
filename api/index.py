from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

# =====================================================================
# CONFIGURAÇÕES DE AMBIENTE (Painel Vercel)
# =====================================================================
VERCEL_BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
DATABASE_URL = os.environ.get("POSTGRES_URL")


# =====================================================================
# INFRAESTRUTURA DE BANCO DE DADOS (PostgreSQL - Neon)
# =====================================================================
def obter_conexao():
    if not DATABASE_URL:
        raise ValueError("A string de conexão (POSTGRES_URL) não foi configurada na Vercel.")

    url_conexao = DATABASE_URL
    if "sslmode" not in url_conexao and "?" in url_conexao:
        url_conexao += "&sslmode=require"
    elif "sslmode" not in url_conexao:
        url_conexao += "?sslmode=require"

    conn = psycopg2.connect(url_conexao, cursor_factory=RealDictCursor, connect_timeout=10)
    conn.autocommit = True
    return conn


def inicializar_infraestrutura_banco():
    if DATABASE_URL:
        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS produtos (
                    id_produto TEXT PRIMARY KEY,
                    nome TEXT,
                    preco NUMERIC,
                    categoria TEXT,
                    foto TEXT,
                    visivel BOOLEAN DEFAULT TRUE
                );
            """)
            cursor.close()
            conn.close()
            print("Infraestrutura do banco de dados verificada/criada com sucesso.")
        except Exception as e:
            print(f"Aviso importante: O banco de dados está inacessível no momento. Detalhes: {str(e)}")


inicializar_infraestrutura_banco()


# =====================================================================
# ROTA: Autenticação Administrativa
# =====================================================================
@app.route("/api/admin/login", methods=["POST"])
def efetuar_login_administrativo():
    dados = request.get_json() or {}
    senha_digitada = dados.get("senha")

    if not ADMIN_PASSWORD:
        return jsonify({"auth": False, "error": "Senha mestra não configurada no servidor."}), 500

    if str(senha_digitada).strip() == str(ADMIN_PASSWORD).strip():
        return jsonify({
            "auth": True,
            "token": "Bearer sessao_valida_lari_premium"
        }), 200

    return jsonify({"auth": False, "error": "Credencial inválida."}), 401


# =====================================================================
# ROTAS: Gerenciamento do Catálogo (Listagem e Persistência Multi-Imagem)
# =====================================================================
@app.route("/api/produtos", methods=["GET", "POST"])
def gerenciar_catalogo_produtos():
    if request.method == "POST":
        token_sessao = request.headers.get("Authorization")
        if token_sessao != "Bearer sessao_valida_lari_premium":
            return jsonify({"error": "Acesso não autorizado."}), 403

        # Lendo os dados textuais do multipart/form-data
        id_produto = request.form.get("id_produto")
        nome = request.form.get("nome")
        preco = request.form.get("preco")
        categoria = request.form.get("categoria")
        visivel = request.form.get("visivel", "true").lower() == "true"

        # Captura múltiplos arquivos sob a mesma chave 'foto'
        arquivos_imagem = request.files.getlist("foto")

        if not id_produto or not nome or preco is None or not categoria:
            return jsonify({"error": "Preencha todos os campos obrigatórios."}), 400

        urls_fotos = []

        try:
            # Faz o upload iterativo de cada arquivo para a infraestrutura da Vercel
            if arquivos_imagem and any(f.filename != '' for f in arquivos_imagem):
                for arquivo in arquivos_imagem:
                    if arquivo.filename == "":
                        continue
                    
                    if not VERCEL_BLOB_READ_WRITE_TOKEN:
                        return jsonify({"error": "Token do Vercel Blob não configurado."}), 500

                    # Evita colisões de nomes usando um sufixo pseudo-aleatório seguro
                    nome_seguro = f"lari_{id_produto}_{os.urandom(2).hex()}_{arquivo.filename}"
                    url_blob = f"https://blob.vercel-storage.com/{nome_seguro}"

                    headers_blob = {
                        "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
                        "x-api-version": "1"
                    }

                    conteudo_arquivo = arquivo.read()
                    resposta_vercel = requests.put(url_blob, headers=headers_blob, data=conteudo_arquivo)

                    if resposta_vercel.status_code in [200, 201]:
                        dados_resposta = resposta_vercel.json()
                        urls_fotos.append(dados_resposta.get("url"))
                    else:
                        return jsonify({"error": f"Vercel Blob rejeitou uma das imagens: {resposta_vercel.text}"}), 500

            # Une as URLs coletadas separando por uma vírgula exata
            string_fotos_banco = ",".join(urls_fotos) if urls_fotos else ""

            conn = obter_conexao()
            cursor = conn.cursor()
            
            # Se já houver fotos e o admin não enviou novas no POST (ex: edição), mantém as antigas ou atualiza
            if not string_fotos_banco:
                # Faz um UPSERT focado em não apagar as fotos caso esteja apenas editando texto
                cursor.execute("""
                    INSERT INTO produtos (id_produto, nome, preco, categoria, visivel)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id_produto) 
                    DO UPDATE SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, 
                                  categoria = EXCLUDED.categoria, visivel = EXCLUDED.visivel;
                """, (str(id_produto).strip(), str(nome).strip(), float(preco), str(categoria).strip(), bool(visivel)))
            else:
                # UPSERT completo atualizando a nova string de imagens separadas por vírgula
                cursor.execute("""
                    INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id_produto) 
                    DO UPDATE SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, 
                                  categoria = EXCLUDED.categoria, foto = EXCLUDED.foto, 
                                  visivel = EXCLUDED.visivel;
                """, (str(id_produto).strip(), str(nome).strip(), float(preco), str(categoria).strip(), string_fotos_banco, bool(visivel)))

            cursor.close()
            conn.close()
            return jsonify({"status": "success", "message": "Produto e imagens processados com sucesso."}), 200
        except Exception as e:
            return jsonify({"error": f"Erro ao processar persistência no banco: {str(e)}"}), 500

    # Retorna o catálogo
    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM produtos;")
        lista_produtos = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(lista_produtos), 200
    except Exception as e:
        return jsonify({"error": f"Erro ao consultar catálogo no banco de dados: {str(e)}"}), 500


# =====================================================================
# ROTA: Remoção de Produto por ID
# =====================================================================
@app.route("/api/produtos/<path:id_prod>", methods=["DELETE"])
def remover_produto_banco(id_prod):
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    id_limpo = str(id_prod).strip()

    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produtos WHERE id_produto = %s;", (id_limpo,))
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Produto excluído com sucesso."}), 200
    except Exception as e:
        return jsonify({"error": f"Erro ao remover produto: {str(e)}"}), 500


# =====================================================================
# FALLBACK: Captura de rotas residuais
# =====================================================================
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    return jsonify({"error": "Rota nao encontrada no backend"}), 404
