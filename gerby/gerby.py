import os
import re
from flask import Flask, request, session, g, redirect, url_for, abort, render_template

from peewee import *
from playhouse.sqlite_ext import *

FILENAME = "htt.sqlite"

db = SqliteExtDatabase(FILENAME)

# TODO this should be taken from a different package?
# TODO or should the tools and the server be in the same package?
class BaseModel(Model):
  class Meta:
    database = db

class Tag(BaseModel):
  tag = CharField(unique=True, primary_key=True)
  label = CharField(unique=True, null=True)
  active = BooleanField(null=True)
  ref = CharField(null=True)
  type = CharField(null=True)
  html = TextField(null=True)

  # allows us to sort tags according to their reference
  def __gt__(self, other):
    return tuple(map(int, self.ref.split("."))) > tuple(map(int, other.ref.split(".")))

class TagSearch(FTSModel):
  tag = SearchField()
  html = SearchField() # HTML of the statement or (sub)section
  full = SearchField() # HTML of the statement including the proof (if relevant)

  class Meta:
    database = db

class Proof(BaseModel):
  tag = ForeignKeyField(Tag, related_name = "proofs")
  html = TextField(null=True)
  number = IntegerField()

class Dependency(BaseModel):
  tag = ForeignKeyField(Tag, related_name="from")
  to = ForeignKeyField(Tag, related_name="to")

class Footnote(BaseModel):
  label = CharField(unique=True, primary_key=True)
  html = TextField(null=True)

class Extra(BaseModel):
  tag = ForeignKeyField(Tag)
  html = TextField(null=True)

class LabelName(BaseModel):
  tag = ForeignKeyField(Tag)
  name = CharField()


# Flask setup code
app = Flask(__name__)
app.config.from_object(__name__)

app.config.update(dict(
  DATABASE=os.path.join(app.root_path, "stacks.sqlite"),
))

@app.route("/")
def show_tags():
  tags = Tag.select()

  return render_template("show_tags.html", tags=tags)

"""
static pages
"""
@app.route("/about")
def show_about():
  return render_template("static/about.html")

"""
dynamic pages
"""
@app.route("/browse")
def show_chapters():
  chapters = Tag.select(Tag.tag, Tag.ref, LabelName.name).join(LabelName).where(Tag.type == "chapter")
  chapters = sorted(chapters)

  return render_template("show_chapters.html", chapters=chapters)

@app.route("/search", methods = ["GET"])
def show_search():
  # TODO not sure whether this is an efficient query: only fulltext and docid is quick apparently
  # TODO can we use TagSearch.docid and Tag.rowid or something?
  # TODO can we match on a single column? maybe we need two tables?

  #/search/?query=...
  print(request.args)

  # TODO suggestion by Max: make sure that if someone searches for a tag in the search field, you return the tag
  # = get rid of the tag lookup field
  # TODO suggestion by Brian: implement different spellings of words, à la Google

  query = "Eilenberg"
  results = Tag.select(Tag, TagSearch, TagSearch.rank().alias("score")).join(TagSearch, on=(Tag.tag == TagSearch.tag).alias("search")).where(TagSearch.match(query), Tag.type.not_in(["chapter", "section", "subsection"]))
  return render_template("show_search.html", results=results)

@app.route("/tag/<string:tag>")
# TODO we also need to support the old format of links!
def show_tag(tag):
  tag = Tag.get(Tag.tag == tag)

  if tag.type == "chapter":
    sections = Tag.select(Tag.tag, Tag.ref, LabelName.name).join(LabelName).where(Tag.type == "section", Tag.ref.startswith(tag.ref + "."))
    sections = sorted(sections)

    # to avoid n+1 query we select all tags at once and then let Python figure it out
    tags = Tag.select().where(Tag.ref.startswith(tag.ref + "."), Tag.type != "section")
    tags = sorted(tags)
    for section in sections:
      section.tags = [tag for tag in tags if tag.ref.startswith(section.ref + ".")]

    return render_template("show_chapter.html", chapter=tag, sections=sections)

  else:
    # TODO maybe always generate the breadcrumb data, but only pass it if at least 3 levels deep?
    # we could have a top breadcrumb if 3 levels deep
    # and an "overview where you're at", on the right now, as many levels as necessary?

    # if something is at least 3 levels deep we show a breadcrumb
    breadcrumb = None
    if len(tag.ref.split(".")) > 2:
      parents = [".".join(tag.ref.split(".")[:-1])]
      while parents[-1] != "":
        parents.append(".".join(parents[-1].split(".")[:-1]))

      # TODO can we do a select with join without specifying all the columns?
      breadcrumb = sorted(Tag.select(Tag.tag, Tag.ref, Tag.type, LabelName.name).join(LabelName).where(Tag.ref << parents))

    # if something is a section, we allow people to navigate by section
    sections = None
    if tag.type == "section":
      # TODO just put in an extra column in Tag, with the in-text order of things, to make life easier...
      pass

    proofs = Proof.select().where(Proof.tag == tag.tag)

    # handle footnotes
    """<a class="footnotemark" href="#{{ obj.id }}" id="{{ obj.id }}-mark"><sup>{{ obj.mark.attributes.num }}</sup></a>"""
    pattern = re.compile("class=\"footnotemark\" href=\"#(a[0-9]+)\"")

    html = tag.html + "".join([proof.html for proof in proofs])

    labels = pattern.findall(html)
    for number, label in enumerate(labels):
      # TODO this is not how regexes should be used... (if you need test material when fixing this, see tag 05QM)
      old = re.search(r"id=\"" + label + "-mark\"><sup>([0-9]+)</sup>", html).group(1)
      html = html.replace(
          "id=\"" + label + "-mark\"><sup>" + old + "</sup>",
          "id=\"" + label + "-mark\"><sup>" + str(number + 1) + "</sup>")
      # make the HTML pretty (and hide plasTeX id's)
      html = html.replace(label, "footnote-" + str(number + 1))

    footnotes = Footnote.select().where(Footnote.label << labels)

    return render_template("show_tag.html", tag=tag, breadcrumb=breadcrumb, html=html, footnotes=footnotes)
