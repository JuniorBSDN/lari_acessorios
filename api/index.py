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
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSOWORD")
DATABASE_URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or os.environ.get(
    "POSTGRES_URL_NON_POOLING")


# =====================================================================
# INFRAESTRUTURA DE BANCO DE DADOS (PostgreSQL)
# =====================================================================
def obter_conexao():
    if not DATABASE_URL:
        raise ValueError("A string de conexão (POSTGRES_URL) não foi configurada na Vercel.")

    # Adiciona automaticamente o parâmetro de SSL caso seja um banco em nuvem (Neon, Render, etc)
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
            # Blindagem: se o banco falhar na partida, o app não morre.
            print(f"Aviso importante: O banco de dados está inacessível no momento. Detalhes: {str(e)}")


# Tenta inicializar sem travar o escopo global se houver timeout
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

    if str(senha_digitada) == str(ADMIN_PASSWORD):
        return jsonify({
            "auth": True,
            "token": "Bearer sessao_valida_lari_premium"
        }), 200

    return jsonify({"auth": False, "error": "Credencial inválida."}), 401


# =====================================================================
# ROTA: Upload de Imagens (Vercel Blob Storage)
# =====================================================================
@app.route("/api/upload", methods=["POST"])
def realizar_upload_imagem():
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    if "foto" not in request.files:
        return jsonify({"error": "Nenhum arquivo de imagem foi enviado."}), 400

    arquivo = request.files["foto"]
    if arquivo.filename == "":
        return jsonify({"error": "Arquivo sem nome válido."}), 400

    if not VERCEL_BLOB_READ_WRITE_TOKEN:
        return jsonify({"error": "Token do Vercel Blob não configurado."}), 500

    try:
        nome_arquivo = arquivo.filename
        conteudo_arquivo = arquivo.read()

        # 1. URL correta dedicada ao Vercel Blob Storage
        url_blob = f"https://blob.vercel-storage.com/{nome_arquivo}"
        
        # 2. Cabeçalhos obrigatórios incluindo a versão da API
        headers_blob = {
            "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
            "x-api-version": "1"
        }

        # 3. Envio usando PUT (enviando os bytes brutos do arquivo)
        resposta_vercel = requests.put(url_blob, headers=headers_blob, data=conteudo_arquivo)

        if resposta_vercel.status_code not in [200, 201]:
            return jsonify({"error": f"Vercel Blob rejeitou o upload: {resposta_vercel.text}"}), 500

        dados_resposta = resposta_vercel.json()
        return jsonify({"url": dados_resposta.get("url")}), 200

    except Exception as e:
        return jsonify({"error": f"Falha no processo de upload: {str(e)}"}), 500


# =====================================================================
# ROTAS: Gerenciamento do Catálogo (Listagem e Persistência)
# =====================================================================
@app.route("/api/produtos", methods=["GET", "POST"])
def gerenciar_catalogo_produtos():
    if request.method == "POST":
        token_sessao = request.headers.get("Authorization")
        if token_sessao != "Bearer sessao_valida_lari_premium":
            return jsonify({"error": "Acesso não autorizado."}), 403

        dados = request.get_json() or {}
        id_produto = dados.get("id_produto")
        nome = dados.get("nome")
        preco = dados.get("preco")
        categoria = dados.get("categoria")
        foto = dados.get("foto")
        visivel = dados.get("visivel", True)

        if not id_produto or not nome or preco is None or not categoria or not foto:
            return jsonify({"error": "Preencha todos os campos obrigatórios."}), 400

        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_produto) 
                DO UPDATE SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, 
                              categoria = EXCLUDED.categoria, foto = EXCLUDED.foto, 
                              visivel = EXCLUDED.visivel;
            """, (str(id_produto), str(nome), float(preco), str(categoria), str(foto), bool(visivel)))
            cursor.close()
            conn.close()
            return jsonify({"status": "success", "message": "Produto salvo com sucesso."}), 200
        except Exception as e:
            return jsonify({"error": f"Erro ao salvar no banco: {str(e)}"}), 500

    # Método GET
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
# FALLBACK: Rota residual
# =====================================================================
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    return jsonify({"error": "Rota nao encontrada no backend"}), 404
