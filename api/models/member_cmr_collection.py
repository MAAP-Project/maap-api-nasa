# from api.maap_database import db
# from datetime import datetime
#
#
# class MemberCmrCollection(db.Model):
#     __tablename__ = 'member_cmr_collection'
#
#     id = db.Column(db.Integer, primary_key=True)
#     member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
#     collection_id = db.Column(db.String())
#     collection_short_name = db.Column(db.String())
#     creation_date = db.Column(db.DateTime())
#
#     member = db.relationship('Member', backref=db.backref('member_collection', lazy=True))
#
#     def __init__(self, member_id, collection_id, collection_short_name):
#         self.member_id = member_id
#         self.collection_id = collection_id
#         self.collection_short_name = collection_short_name
#         self.creation_date = datetime.utcnow()
#
#     def __repr__(self):
#         return '<MemberCmrCollection %r>' % self.collection_id
