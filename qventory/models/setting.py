from ..extensions import db

class Setting(db.Model):
    __tablename__ = "settings"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False, index=True)

    enable_A = db.Column(db.Boolean, default=True)
    enable_B = db.Column(db.Boolean, default=True)
    enable_S = db.Column(db.Boolean, default=True)
    enable_C = db.Column(db.Boolean, default=True)

    label_A = db.Column(db.String, default="Aisle")
    label_B = db.Column(db.String, default="Bay")
    label_S = db.Column(db.String, default="Shelve")
    label_C = db.Column(db.String, default="Container")
    theme_preference = db.Column(db.String(20), default="dark")
    link_bio_slug = db.Column(db.String(60), nullable=True, unique=True, index=True)
    link_bio_image_url = db.Column(db.String, nullable=True)
    link_bio_bio = db.Column(db.Text, nullable=True)
    link_bio_links_json = db.Column(db.Text, nullable=True)
    link_bio_featured_json = db.Column(db.Text, nullable=True)

    def enabled_levels(self):
        levels = []
        if self.enable_A: levels.append("A")
        if self.enable_B: levels.append("B")
        if self.enable_S: levels.append("S")
        if self.enable_C: levels.append("C")
        return levels

    def labels_map(self):
        return {"A": self.label_A, "B": self.label_B, "S": self.label_S, "C": self.label_C}
