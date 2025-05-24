import gridfs
from flask import send_file  
from flask import Flask, render_template, redirect, url_for, request, flash, send_from_directory, session
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash, send_from_directory, session, jsonify
import os

from config import Config
app = Flask(__name__)

app.config.from_object(Config)


mongo = PyMongo(app)
fs = gridfs.GridFS(mongo.db)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# User model
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']
        self.role = user_data['role']
        self.email = user_data.get('email', '')
        self.subscribed_artists = user_data.get('subscribed_artists', [])



@login_manager.user_loader
def load_user(user_id):
    user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    return User(user_data) if user_data else None

# ------------------------- ROUTES -------------------------

@app.route('/')
def index():
    artists = mongo.db.artists.find()
    return render_template('index.html', artists=artists)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_data = mongo.db.users.find_one({'email': request.form['email']})
        if user_data and bcrypt.check_password_hash(user_data['password'], request.form['password']):
            login_user(User(user_data))


            if user_data['email'].endswith('@drexel.edu'):
            # If the user has no subscriptions yet, go to choose_artists
                if not user_data.get('subscribed_artists'):
                    return redirect(url_for('choose_artists'))
                return redirect(url_for('your_artists'))

            # General users check if they've already subscribed
            if user_data.get('subscribed_artists'):
                return redirect(url_for('your_artists'))
            else:
                return redirect(url_for('plans'))

        flash('Invalid login credentials.')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')

        # Insert into DB without checking for @drexel.edu
        mongo.db.users.insert_one({
            'username': username,
            'email': email,
            'password': password,
            'role': 'fan'
        })
        flash('Registration successful. Please login.')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/artists/login', methods=['GET', 'POST'])
def artist_login():
    if request.method == 'POST':
        user_data = mongo.db.users.find_one({'username': request.form['username'], 'role': 'artist'})
        if user_data and bcrypt.check_password_hash(user_data['password'], request.form['password']):
            login_user(User(user_data))

            # Fetch artist details and check for missing profile info
            artist_data = mongo.db.artists.find_one({'username': user_data['username']})
            if not artist_data or not artist_data.get('genre') or not artist_data.get('bio'):
                return redirect(url_for('complete_profile'))

            return redirect(url_for('dashboard'))
        flash('Invalid artist credentials.')
    return render_template('artist_login.html')

@app.route('/artists/register', methods=['GET', 'POST'])
def artist_register():
    if request.method == 'POST':
        username = request.form['username']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        mongo.db.users.insert_one({'username': username, 'password': password, 'role': 'artist'})
        mongo.db.artists.insert_one({'username': username, 'bio': '', 'media': []})
        flash('Artist registered. Please login.')
        return redirect(url_for('artist_login'))
    return render_template('artist_register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'artist':
        artist = mongo.db.artists.find_one({'username': current_user.username})
        uploads = artist.get('media', [])

        # Extract and attach file extensions for display logic
        for media in uploads:
            if media.get("media_file_id"):
                try:
                    grid_out = fs.get(media["media_file_id"])
                    # Don't overwrite filename if it already exists
                    if not media.get("filename"):
                        media["filename"] = grid_out.filename.lower()
                    if not media.get("media_filename"):
                        media["media_filename"] = grid_out.filename.lower()
                except:
                    media["media_filename"] = media.get("filename", "")
            else:
                media["media_filename"] = media.get("filename", "")


        upload_count = len(uploads)
        total_plays = sum(m.get('plays', 0) for m in uploads)
        total_likes = sum(len(m.get('likes', [])) for m in uploads)
        total_comments = sum(len(m.get('comments', [])) for m in uploads)

        timestamps = [m.get('upload_time') for m in uploads if isinstance(m, dict) and 'upload_time' in m]
        latest_upload = max(timestamps) if timestamps else None

        artist['media'] = uploads  # ensure you're assigning the updated media list back

        return render_template(
            'artist_dashboard.html',
            artist=artist,
            upload_count=upload_count,
            total_plays=total_plays,
            total_likes=total_likes,
            total_comments=total_comments,
            latest_upload=latest_upload
        )
    else:
        artists = mongo.db.artists.find()
        return render_template('fan_dashboard.html', artists=artists)



@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/artists')
def all_artists():
    artists = mongo.db.artists.find()
    return render_template('all_artists.html', artists=artists)

@app.route('/artist/<artist_id>')
def artist_profile(artist_id):
    artist = mongo.db.artists.find_one({'_id': ObjectId(artist_id)})
    if not artist:
        flash('Artist not found.', 'error')
        return redirect(url_for('all_artists'))

    # Inject GridFS filenames
    for media in artist.get('media', []):
        if media.get("media_file_id"):
            try:
                grid_out = fs.get(media["media_file_id"])
                media["filename"] = grid_out.filename.lower()  # for playback logic
            except:
                media["filename"] = ""
        else:
            media["filename"] = ""

    # Analytics data
    media_count = len(artist.get('media', []))
    last_upload = max((m.get('upload_time') for m in artist['media'] if m.get('upload_time')), default=None)
    subscriber_count = mongo.db.users.count_documents({'subscribed_artists': str(artist['_id'])})
    total_likes = sum(len(m.get('likes', [])) for m in artist.get('media', []))

    return render_template(
        'artist_profile.html',
        artist=artist,
        subscriber_count=subscriber_count,
        media_count=media_count,
        last_upload=last_upload,
        total_likes=total_likes
    )


@app.route('/plans')
def plans():
    return render_template('plans.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/choose_artists', methods=['GET'])
@login_required
def choose_artists():
    artists = mongo.db.artists.find()
    return render_template('choose_artists.html', artists=artists)

@app.route('/confirm_drexel')
@login_required
def drexel_confirm():
    if not current_user.email.endswith('@drexel.edu'):
        flash('Access denied. You are not a Drexel student.', 'error')
        return redirect(url_for('plans'))
    flash('Welcome to the Inner Circle! Enjoy the artists 🎨🔥', 'success')
    return redirect(url_for('all_artists'))

@app.route('/confirm_general')
@login_required
def general_confirm():
    if current_user.email.endswith('@drexel.edu'):
        flash('You are already on Drexel free plan!', 'info')
        return redirect(url_for('all_artists'))
    if current_user.subscribed_artists:
        return redirect(url_for('your_artists'))
    return render_template('choose_artists.html')

@app.route('/process_subscription', methods=['POST'])
@login_required
def process_subscription():
    selected_artist_ids = request.form.getlist('selected_artists')

    # Save selected artists to the user's profile
    mongo.db.users.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$set': {'subscribed_artists': selected_artist_ids}}
    )

    # Optional: store in session if needed
    session['selected_artists'] = selected_artist_ids

    flash('Artists selected. Welcome to your Circle!', 'success')
    return redirect(url_for('your_artists'))



@app.route('/payment')
@login_required
def payment_page():
    return render_template('payment.html')

@app.route('/your_artists')
@login_required
def your_artists():
    artist_ids = getattr(current_user, 'subscribed_artists', [])
    
    if not artist_ids:
        artists = []
    else:
        artists = mongo.db.artists.find({'_id': {'$in': [ObjectId(aid) for aid in artist_ids]}})

    return render_template('your_artists.html', artists=artists)


import mimetypes

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    if current_user.role != 'artist':
        flash('Only artists can upload.')
        return redirect(url_for('dashboard'))

    title = request.form.get('title')
    description = request.form.get('description')
    media_file = request.files['file']
    artwork_file = request.files.get('artwork')

    if not media_file or not title or not description:
        flash('Missing required fields.')
        return redirect(url_for('dashboard'))

    filename_cleaned = secure_filename(media_file.filename)

    try:
        media_file_id = fs.put(media_file.stream, filename=filename_cleaned)
    except Exception as e:
        flash(f'Upload failed: {str(e)}')
        return redirect(url_for('dashboard'))

    media_type = mimetypes.guess_type(media_file.filename)[0] or "application/octet-stream"

    artwork_file_id = None
    if artwork_file and artwork_file.filename:
        try:
            artwork_file_id = fs.put(artwork_file.stream, filename=secure_filename(artwork_file.filename))
        except:
            artwork_file_id = None

    new_media_entry = {
        "_id": ObjectId(),
        "title": title,
        "description": description,
        "filename": filename_cleaned,              # <-- permanent, used in likes/comments
        "media_filename": filename_cleaned,        # <-- optional: used by template
        "media_file_id": media_file_id,
        "media_type": media_type,
        "artwork_file_id": artwork_file_id,
        "plays": 0,
        "likes": [],
        "comments": [],
        "upload_time": datetime.now()
    }

    mongo.db.artists.update_one(
        {'username': current_user.username},
        {'$push': {'media': new_media_entry}}
    )

    flash('Upload successful!')
    return redirect(url_for('dashboard'))


@app.route('/increment_play/<artist_id>/<filename>', methods=['POST'])
@login_required
def increment_play(artist_id, filename):
    artist = mongo.db.artists.find_one({'_id': ObjectId(artist_id)})
    if not artist:
        return '', 404

    updated_media = []
    for media in artist['media']:
        if isinstance(media, dict) and media.get('filename') == filename:
            media['plays'] = media.get('plays', 0) + 1
        updated_media.append(media)

    mongo.db.artists.update_one({'_id': ObjectId(artist_id)}, {'$set': {'media': updated_media}})
    return '', 204  # No content


@app.route('/like', methods=['POST'])
@login_required
def like_media():
    data = request.get_json()
    artist_id = data['artist_id']
    media_id = data['media_id']

    artist = mongo.db.artists.find_one({'_id': ObjectId(artist_id)})
    if not artist:
        return jsonify(success=False), 404

    updated_media = []
    liked = False
    for media in artist['media']:
        if str(media.get('_id')) == media_id:
            user_id = str(current_user.id)
            if 'likes' not in media or not isinstance(media['likes'], list):
                media['likes'] = []

            if user_id in media['likes']:
                media['likes'].remove(user_id)
                liked = False
            else:
                media['likes'].append(user_id)
                liked = True
        updated_media.append(media)

    mongo.db.artists.update_one({'_id': ObjectId(artist_id)}, {'$set': {'media': updated_media}})
    return jsonify(success=True, liked=liked, likes=len(media['likes']))


@app.route('/comment/<artist_id>/<media_id>', methods=['POST'])
@login_required
def add_comment(artist_id, media_id):
    text = request.form.get('comment_text')
    if not text:
        return redirect(request.referrer)

    artist = mongo.db.artists.find_one({'_id': ObjectId(artist_id)})
    if not artist:
        return "Artist not found", 404

    for media in artist['media']:
        if str(media.get('_id')) == media_id:
            if 'comments' not in media:
                media['comments'] = []
            media['comments'].append({
                'user_id': current_user.id,
                'username': current_user.username,
                'text': text,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
            })
            break

    mongo.db.artists.update_one(
        {'_id': ObjectId(artist_id)},
        {'$set': {'media': artist['media']}}
    )

    return redirect(request.referrer)

@app.route('/file/<file_id>')
def get_file(file_id):
    try:
        file = fs.get(ObjectId(file_id))
        return send_file(file, download_name=file.filename)
    except:
        return "File not found", 404

@app.route('/complete_profile', methods=['GET', 'POST'])
@login_required
def complete_profile():
    if current_user.role != 'artist':
        flash('Only artists need to complete a profile.', 'error')
        return redirect(url_for('dashboard'))

    artist = mongo.db.artists.find_one({'username': current_user.username})

    # If already filled, redirect to dashboard
    if artist and artist.get('genre') and artist.get('bio'):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        genre = request.form['genre']
        bio = request.form['bio']

        mongo.db.artists.update_one(
            {'username': current_user.username},
            {'$set': {'genre': genre, 'bio': bio}}
        )
        flash('Profile completed successfully!')
        return redirect(url_for('dashboard'))

    return render_template('complete_profile.html')

@app.route('/delete_media/<media_id>', methods=['POST'])
@login_required
def delete_media(media_id):
    if current_user.role != 'artist':
        flash('Only artists can delete media.')
        return redirect(url_for('dashboard'))

    artist = mongo.db.artists.find_one({'username': current_user.username})
    if not artist:
        flash('Artist not found.')
        return redirect(url_for('dashboard'))

    updated_media = []
    for media in artist.get('media', []):
        if str(media.get('_id')) == media_id:
            # Delete files from GridFS
            if media.get('media_file_id'):
                try:
                    fs.delete(ObjectId(media['media_file_id']))
                except:
                    pass
            if media.get('artwork_file_id'):
                try:
                    fs.delete(ObjectId(media['artwork_file_id']))
                except:
                    pass
            continue  # skip adding this media
        updated_media.append(media)

    mongo.db.artists.update_one(
        {'username': current_user.username},
        {'$set': {'media': updated_media}}
    )

    flash('Media deleted successfully!')
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    app.run(debug=True)
