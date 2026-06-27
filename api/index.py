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
# Alinhamento milimétrico com o seu painel de variáveis
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
    # Força o uso de conexões seguras exigidas pelo Neon
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
            # Garante a criação exata da tabela do catálogo
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


# Inicialização automática da tabela no deploy
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

        # URL de destino do arquivo na infraestrutura da Vercel
        url_blob = f"https://blob.vercel-storage.com/{nome_arquivo}"
        
        headers_blob = {
            "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
            "x-api-version": "1"
        }

        # Transmissão dos bytes puros via PUT
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

        # Validação milimétrica dos campos obrigatórios em português
        if not id_produto or not nome or preco is None or not categoria or not foto:
            return jsonify({"error": "Preencha todos os campos obrigatórios."}), 400

        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            # Tratamento de conflito (UPSERT) para atualizar se o ID já existir
            cursor.execute("""
                INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_produto) 
                DO UPDATE SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, 
                              categoria = EXCLUDED.categoria, foto = EXCLUDED.foto, 
                              visivel = EXCLUDED.visivel;
            """, (str(id_produto).strip(), str(nome).strip(), float(preco), str(categoria).strip(), str(foto).strip(), bool(visivel)))
            cursor.close()
            conn.close()
            return jsonify({"status": "success", "message": "Produto salvo com sucesso."}), 200
        except Exception as e:
            return jsonify({"error": f"Erro ao salvar no banco: {str(e)}"}), 500

    # Chamada GET: Retorna a lista completa do catálogo em formato JSON estável
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
