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

        # Captura os dados vindos via FormData (request.form)
        id_produto = request.form.get("id_produto")
        nome = request.form.get("nome")
        preco = request.form.get("preco")
        categoria = request.form.get("categoria")
        visivel_raw = request.form.get("visivel", "true")
        foto_antiga = request.form.get("foto_antiga", "")

        # Conversão segura do estado de visibilidade
        if visivel_raw == "vendido":
            visivel = "vendido"
        else:
            visivel = visivel_raw.lower() in ["true", "1", "yes"]

        if not id_produto or not nome or preco is None or not categoria:
            return jsonify({"error": "Preencha todos os campos obrigatórios."}), 400

        lista_urls_fotos = []

        # Processamento das imagens enviadas
        arquivos = request.files.getlist("foto")
        if arquivos and arquivos[0].filename != "":
            if not VERCEL_BLOB_READ_WRITE_TOKEN:
                return jsonify({"error": "Token do Vercel Blob não configurado."}), 500

            try:
                for arquivo in arquivos:
                    nome_arquivo = f"{id_produto}_{arquivo.filename}"
                    conteudo_arquivo = arquivo.read()
                    url_blob = f"https://blob.vercel-storage.com/{nome_arquivo}"

                    headers_blob = {
                        "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
                        "x-api-version": "1"
                    }

                    resposta_vercel = requests.put(url_blob, headers=headers_blob, data=conteudo_arquivo)

                    if resposta_vercel.status_code in [200, 201]:
                        lista_urls_fotos.append(resposta_vercel.json().get("url"))
                    else:
                        return jsonify({"error": f"Vercel Blob rejeitou o upload: {resposta_vercel.text}"}), 500

                # Junta as novas fotos separadas por vírgula
                string_fotos = ",".join(lista_urls_fotos)
            except Exception as e:
                return jsonify({"error": f"Falha no upload das imagens: {str(e)}"}), 500
        else:
            # Caso não tenha enviado novas fotos, mantém as que já existiam (Edição)
            string_fotos = foto_antiga

        if not string_fotos:
            return jsonify({"error": "É necessário incluir ao menos uma imagem para o produto."}), 400

        try:
            conn = obter_conexao()
            cursor = conn.cursor()

            # Ajuste dinâmico do tipo do campo 'visivel' (aceitando TEXT para 'vendido' ou BOOLEAN mapeado)
            cursor.execute("""
                INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_produto) 
                DO UPDATE SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, 
                              categoria = EXCLUDED.categoria, foto = EXCLUDED.foto, 
                              visivel = EXCLUDED.visivel;
            """, (str(id_produto).strip(), str(nome).strip(), float(preco), str(categoria).strip(), string_fotos,
                  str(visivel)))

            cursor.close()
            conn.close()
            return jsonify({"status": "success", "message": "Produto salvo com sucesso."}), 200
        except Exception as e:
            return jsonify({"error": f"Erro ao salvar no banco: {str(e)}"}), 500

    # Chamada GET: Retorna a lista completa do catálogo
    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM produtos;")
        lista_produtos = cursor.fetchall()

        # Garante a conformidade do tipo booleano/texto ao ler do banco para evitar bugs na vitrine
        for p in lista_produtos:
            if p['visivel'] == 'True':
                p['visivel'] = True
            elif p['visivel'] == 'False':
                p['visivel'] = False

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
